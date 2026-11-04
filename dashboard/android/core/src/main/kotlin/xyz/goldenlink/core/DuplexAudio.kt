package xyz.goldenlink.core

/** WebRTC PCM 두 방향을 16kHz 모노/100ms 블록으로 합친다. 오디오 큐 하나에서 호출한다. */
class DuplexAudio {
    private val near = ArrayList<Float>()
    private val far = ArrayList<Float>()
    private var nearPhase = 0.0
    private var farPhase = 0.0

    fun append(samples: FloatArray, rate: Int, remote: Boolean): FloatArray {
        if (rate <= 0) return floatArrayOf()
        val target = if (remote) far else near
        var phase = if (remote) farPhase else nearPhase
        for (sample in samples) {
            phase += 16000
            while (phase >= rate) { target.add(sample); phase -= rate }
        }
        if (remote) farPhase = phase else nearPhase = phase
        return drain(false)
    }

    fun drain(final: Boolean): FloatArray {
        val max = maxOf(near.size, far.size)
        val count = if (final) max else if (max > 16000) max - 8000 else minOf(near.size, far.size) / 1600 * 1600
        if (count <= 0) return floatArrayOf()
        val result = FloatArray(count) { ((near.getOrElse(it) { 0f } + far.getOrElse(it) { 0f }) * .5f).coerceIn(-1f, 1f) }
        near.subList(0, minOf(count, near.size)).clear()
        far.subList(0, minOf(count, far.size)).clear()
        return result
    }
}
