package xyz.goldenlink.core

import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.time.Instant
import java.time.ZoneId
import java.util.UUID

// [기록] 탭 — 지난 사건과 그 사건의 병원 응답·인계확인서의 날짜별 로컬 복사본. hub 보관소와 epoch·변경 순번으로 동기화한다(아이폰 CaseRecord.swift와 같다).
// 병원 이벤트는 최신 상태와 별도로 보존한다.

/** hub 보관소는 epoch ms를 소수가 붙은 실수로 줄 수 있다 — 정수든 실수든 Long으로 받는다 */
object EpochMsSerializer : KSerializer<Long> {
    override val descriptor = PrimitiveSerialDescriptor("EpochMs", PrimitiveKind.LONG)
    override fun deserialize(decoder: Decoder): Long {
        val p = (decoder as JsonDecoder).decodeJsonElement().jsonPrimitive
        return p.longOrNull ?: p.double.toLong()
    }
    override fun serialize(encoder: Encoder, value: Long) = encoder.encodeLong(value)
}

/** 병원이 이 사건에 한 응답 — hub 매칭 결과의 status 그대로 모은다 */
enum class ResponseGroup(val label: String) {
    CONFIRMED("이송 확정"), APPROVED("수용 승인"), REJECTED("거부"), NO_REPLY("무응답");

    companion object {
        /** pending(응답 없음)은 무응답으로 센다. 수용 승인했지만 선택되지 않은 병원은 따로 둔다 */
        fun of(status: String): ResponseGroup = when (status) {
            "confirmed" -> CONFIRMED
            "approved" -> APPROVED
            "rejected" -> REJECTED
            else -> NO_REPLY
        }
    }
}

@Serializable
data class RecordHospital(
    val hospitalId: String,
    val name: String,
    val status: String = "pending",
    val rejectReason: String? = null,
    val distanceKm: Double? = null,
    val etaMin: Double? = null,
) {
    val group: ResponseGroup get() = ResponseGroup.of(status)
}

/** 사건 하나의 기록. `handover`는 자동값에 구급대원이 고친 칸을 얹은 최종 값(칸 id → 값) */
@Serializable
data class CaseRecord(
    val caseId: String,
    val apid: String? = null,
    val ambulanceName: String? = null,
    /** 사건 시작 날짜(KST, yyyy-MM-dd) — 날짜별 목록의 키 */
    val date: String,
    /** 사건 시작 시각(epoch ms) */
    @Serializable(with = EpochMsSerializer::class) val startedAt: Long,
    @Serializable(with = EpochMsSerializer::class) val updatedAt: Long,
    val symptom: String? = null,
    val expectedDiagnosis: String? = null,
    val ktasLevel: Int? = null,
    val hospitals: List<RecordHospital> = emptyList(),
    val handover: Map<String, String> = emptyMap(),
    val closed: Boolean = false,
    /** 서버 변경 순번. null이면 기기에만 있던 과거 기록이다 */
    val archiveVersion: Int? = null,
    val archiveEpoch: String? = null,
    val handoverRevision: Int? = null,
    val handoverEdits: Map<String, String>? = null,
    val events: List<HospitalRecordEvent>? = null,
    val legacyImport: Boolean? = null,
) {
    fun count(group: ResponseGroup): Int = hospitals.count { it.group == group }
}

object RecordDates {
    val zone: ZoneId = ZoneId.of("Asia/Seoul")

    fun of(epochMs: Long): String = Instant.ofEpochMilli(epochMs).atZone(zone).toLocalDate().toString()

    fun timeOf(epochMs: Long): String = Instant.ofEpochMilli(epochMs).atZone(zone).toLocalTime().let { "%02d:%02d".format(it.hour, it.minute) }
}


@Serializable
data class HospitalRecordEvent(
    val id: String,
    val hospitalId: String,
    val action: String,
    val actor: String,
    val timestamp: String,
    val reason: String? = null,
) {
    val label: String get() = when (action) {
        "hospital_approve" -> "수용 승인"
        "hospital_reject" -> "수용 거절"
        "final_approval" -> "이송 확정"
        "transport_withdraw" -> "이송 중 수용 철회"
        "arrival_accepted" -> "도착 후 수용"
        "arrival_refused" -> "도착 후 수용 불가"
        else -> action
    }
}

@Serializable
data class RecordSyncReply(
    val requestId: String? = null,
    val apid: String? = null,
    val epoch: String? = null,
    val cursor: Int? = null,
    val hasMore: Boolean? = null,
    val records: List<CaseRecord>? = null,
    val record: CaseRecord? = null,
    val conflict: Boolean? = null,
    val error: String? = null,
)

@Serializable
data class RecordSyncRequest(val requestId: String, val token: String, val cursor: Int, val epoch: String? = null, val type: String = "record_sync")

@Serializable
data class RecordImportRequest(val requestId: String, val token: String, val records: List<CaseRecord>, val type: String = "record_import")

/** 기기에서 저장한 인계확인서 수정 — 연결이 돌아올 때까지 파일에 보관했다가 같은 requestId로 재전송한다 */
@Serializable
data class PendingHandover(
    val caseId: String,
    val revision: Int,
    val edits: Map<String, String>,
    val requestId: String = UUID.randomUUID().toString(),
)

@Serializable
data class RecordHandoverRequest(
    val requestId: String, val token: String, val caseId: String, val revision: Int, val edits: Map<String, String>,
    val type: String = "record_handover",
) {
    constructor(pending: PendingHandover, token: String) : this(pending.requestId, token, pending.caseId, pending.revision, pending.edits)
}
