package xyz.goldenlink.phone

import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import xyz.goldenlink.core.CaseRecord
import xyz.goldenlink.core.PendingHandover
import xyz.goldenlink.core.hubJson
import java.io.File
import java.security.MessageDigest

/**
 * 서버·구급차별 로컬 복사본(아이폰 RecordStore.swift와 같다). 날짜별 파일(yyyy-MM-dd.json) + 동기화 커서(cursor.json) +
 * 아직 서버에 못 보낸 인계확인서 수정 대기열(outbox.json). 페이지 저장이 성공해야 커서를 전진시킨다.
 * [httpBase]는 hub 주소 — 서버가 바뀌면 다른 폴더를 쓴다.
 */
class RecordStore(private val root: File, private val httpBase: () -> String) {
    private var dir: File = File(root, "unselected")
    var apid: String? = null
        private set
    private val caseDates = HashMap<String, MutableSet<String>>()
    private val legacyIds = HashSet<String>()
    private val listSer = ListSerializer(CaseRecord.serializer())
    private val datePattern = Regex("""^\d{4}-\d{2}-\d{2}$""")

    @Serializable
    data class Cursor(val epoch: String? = null, val cursor: Int = 0)

    @Synchronized
    fun configure(apid: String?) {
        this.apid = apid
        val scope = httpBase() + "|" + (apid ?: "unselected")
        val digest = MessageDigest.getInstance("SHA-256").digest(scope.toByteArray()).joinToString("") { "%02x".format(it) }
        dir = File(root, digest)
        caseDates.clear(); legacyIds.clear()
        for (date in dates()) for (record in load(date)) {
            caseDates.getOrPut(record.caseId) { HashSet() }.add(date)
            if (record.archiveVersion == null) legacyIds.add(record.caseId)
        }
        // 기존 앱의 날짜별 파일은 첫 연결 서버로 이관할 복사본을 만든다. 원본은 삭제하지 않는다.
        if (apid == null) return
        val old = root.listFiles { f -> f.isFile && f.name.matches(Regex("""\d{4}-\d{2}-\d{2}\.json""")) } ?: return
        for (f in old) {
            val list = runCatching { hubJson.decodeFromString(listSer, f.readText()) }.getOrNull() ?: continue
            for (record in list) if (record.apid == apid && byCase(record.caseId) == null) upsert(record)
        }
    }

    /** 기록이 있는 날짜(오름차순) */
    @Synchronized
    fun dates(): List<String> = dir.listFiles { f -> f.isFile && f.name.matches(Regex("""\d{4}-\d{2}-\d{2}\.json""")) }
        ?.map { it.name.removeSuffix(".json") }?.sorted() ?: emptyList()

    /** 그 날짜의 사건(시작 시각 최신순) — 선택한 구급차의 것만 */
    @Synchronized
    fun load(date: String): List<CaseRecord> {
        if (!datePattern.matches(date)) return emptyList()
        val f = File(dir, "$date.json")
        if (!f.isFile) return emptyList()
        return runCatching { hubJson.decodeFromString(listSer, f.readText()) }.getOrDefault(emptyList())
            .filter { it.apid == apid }.sortedByDescending { it.startedAt }
    }

    /** 사건 id로 찾는다 — 연결 때 만든 사건→날짜 색인을 쓴다(매번 전체 기록을 읽지 않는다) */
    @Synchronized
    fun byCase(caseId: String): CaseRecord? =
        (caseDates[caseId] ?: emptySet()).flatMap { load(it) }.filter { it.caseId == caseId }.maxByOrNull { it.updatedAt }

    /** 서버 버전이 없는(기기에만 있던) 기록 20건 — 서버로 이관할 후보 */
    @Synchronized
    fun legacyRecords(): List<CaseRecord> = legacyIds.sorted().take(20).mapNotNull { byCase(it) }

    /** 새 날짜 파일 저장 후에만 예전 날짜의 사본을 정리한다. 실패하면 false — 커서를 유지하고 재시도한다 */
    @Synchronized
    fun upsert(record: CaseRecord): Boolean {
        if (record.apid != apid || !datePattern.matches(record.date)) return false
        if (!write(listSer, load(record.date).filter { it.caseId != record.caseId } + record, "${record.date}.json")) return false
        for (date in caseDates[record.caseId] ?: emptySet()) {
            if (date == record.date) continue
            val list = load(date)
            if (list.any { it.caseId == record.caseId } && !write(listSer, list.filter { it.caseId != record.caseId }, "$date.json")) return false
        }
        caseDates[record.caseId] = hashSetOf(record.date)
        if (record.archiveVersion == null) legacyIds.add(record.caseId) else legacyIds.remove(record.caseId)
        return true
    }

    @get:Synchronized
    val cursor: Cursor get() = read(Cursor.serializer(), "cursor.json") ?: Cursor()

    @Synchronized
    fun saveCursor(value: Cursor): Boolean = write(Cursor.serializer(), value, "cursor.json")

    @get:Synchronized
    val pending: List<PendingHandover> get() = read(ListSerializer(PendingHandover.serializer()), "outbox.json") ?: emptyList()

    @Synchronized
    fun savePending(value: List<PendingHandover>): Boolean = write(ListSerializer(PendingHandover.serializer()), value, "outbox.json")

    private fun <T> read(ser: kotlinx.serialization.KSerializer<T>, name: String): T? {
        val f = File(dir, name)
        if (!f.isFile) return null
        return runCatching { hubJson.decodeFromString(ser, f.readText()) }.getOrNull()
    }

    private fun <T> write(ser: kotlinx.serialization.KSerializer<T>, value: T, name: String): Boolean = runCatching {
        dir.mkdirs()
        // 쓰는 도중 꺼져도 예전 파일이 남도록 임시 파일에 쓴 뒤 바꾼다
        val tmp = File(dir, "$name.tmp")
        tmp.writeText(hubJson.encodeToString(ser, value))
        check(tmp.renameTo(File(dir, name)) || File(dir, name).let { it.delete() && tmp.renameTo(it) })
    }.isSuccess
}

/** 기록 동기화 키 — 서버·구급차별로 기기에 보관한다. 일반 설정·로그에는 기록하지 않는다 */
class RecordAccess(private val settings: Settings) {
    private fun key(apid: String) = "record-token-" + settings.httpBase + "|" + apid
    fun token(apid: String): String = settings.getString(key(apid)) ?: ""
    fun save(token: String, apid: String): Boolean = settings.putString(key(apid), token.trim())
}
