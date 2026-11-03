package xyz.goldenlink.core

/** 구급대 접근 코드(`P-SEL0111`, 아이패드는 `A-SEL0111`) → 구급차 ID. 휴대폰·태블릿이 같은 구급대로 연결된다 — 아이폰 Settings.ambulanceID와 같은 규칙 */
object AccessCode {
    fun ambulanceId(code: String): String? {
        val normalized = code.trim().uppercase()
        if (!(normalized.startsWith("P-") || normalized.startsWith("A-"))) return null
        val id = normalized.drop(2)
        if (id.isEmpty() || id == "AUTO" || !id.all { it in 'A'..'Z' || it in '0'..'9' }) return null
        return id
    }

    /** 병원 접근 코드(`H-A1100017`, hub의 E-Gen 병원 ID) → 병원 ID. 병원 모드(수신 전화)로 들어간다 — 웹 병원 대시보드와 같은 코드 */
    fun hospitalId(code: String): String? {
        val normalized = code.trim().uppercase()
        if (!normalized.startsWith("H-")) return null
        val id = normalized.drop(2)
        if (id.isEmpty() || !id.all { it in 'A'..'Z' || it in '0'..'9' }) return null
        return id
    }
}
