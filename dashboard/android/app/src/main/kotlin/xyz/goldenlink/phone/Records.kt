package xyz.goldenlink.phone

import kotlinx.serialization.builtins.ListSerializer
import xyz.goldenlink.core.CaseRecord
import xyz.goldenlink.core.hubJson
import java.io.File

/** 사건 기록을 날짜별 파일(records/yyyy-MM-dd.json) 하나에 목록으로 둔다. 기기 안에만 저장된다 */
class RecordStore(private val dir: File) {
    private val ser = ListSerializer(CaseRecord.serializer())

    /** 기록이 있는 날짜(오름차순) */
    @Synchronized
    fun dates(): List<String> = dir.listFiles { f -> f.extension == "json" }?.map { it.nameWithoutExtension }?.sorted() ?: emptyList()

    /** 그 날짜의 사건(시작 시각 최신순) */
    @Synchronized
    fun load(date: String): List<CaseRecord> {
        val f = File(dir, "$date.json")
        if (!f.isFile) return emptyList()
        return runCatching { hubJson.decodeFromString(ser, f.readText()) }.getOrDefault(emptyList()).sortedByDescending { it.startedAt }
    }

    /** 날짜를 몰라도 사건 id로 찾는다(최근 날짜부터) */
    fun byCase(caseId: String): CaseRecord? = dates().asReversed().firstNotNullOfOrNull { d -> load(d).firstOrNull { it.caseId == caseId } }

    @Synchronized
    fun upsert(record: CaseRecord) {
        dir.mkdirs()
        val list = load(record.date).filter { it.caseId != record.caseId } + record
        File(dir, "${record.date}.json").writeText(hubJson.encodeToString(ser, list))
    }
}
