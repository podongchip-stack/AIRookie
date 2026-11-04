package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class DuplexAudioTest {
    @Test fun twoDirectionsShareOneTimeline() {
        val audio = DuplexAudio()
        assertEquals(0, audio.append(FloatArray(4800) { .8f }, 48000, false).size)
        val mixed = audio.append(FloatArray(1600) { .2f }, 16000, true)
        assertEquals(1600, mixed.size)
        assertTrue(mixed.all { kotlin.math.abs(it - .5f) < .0001f })
        assertEquals(0, audio.drain(true).size)
    }
    @Test fun fractionalRateAndFlushAreStable() {
        val audio = DuplexAudio()
        repeat(10) { audio.append(FloatArray(441) { 1f }, 44100, false) }
        assertEquals(1600, audio.drain(true).size)
        assertEquals(0, audio.drain(true).size)
    }
    @Test fun missingSideIsBoundedAndPreserved() {
        val audio = DuplexAudio()
        val output = audio.append(FloatArray(32000) { .3f }, 16000, false)
        assertEquals(32000, output.size + audio.drain(true).size)
    }
}
