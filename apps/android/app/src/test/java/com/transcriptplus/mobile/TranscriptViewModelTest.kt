package com.transcriptplus.mobile

import com.transcriptplus.mobile.data.InMemoryProjectRepository
import com.transcriptplus.mobile.domain.formatTime
import com.transcriptplus.mobile.ui.transcript.TranscriptViewModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class TranscriptViewModelTest {
    private fun viewModel() = TranscriptViewModel(InMemoryProjectRepository.sample(), "p1")

    @Test fun commitEditTrimsAndSaves() {
        val vm = viewModel()
        vm.beginEdit(vm.state.value.segments[0])
        vm.commitEdit("  新文字 ")
        assertEquals("新文字", vm.state.value.segments[0].text)
        assertNull(vm.state.value.editing)
    }

    @Test fun emptyEditIsRejected() {
        val vm = viewModel()
        val original = vm.state.value.segments[0].text
        vm.beginEdit(vm.state.value.segments[0])
        vm.commitEdit("   ")
        assertEquals(original, vm.state.value.segments[0].text)
        assertNotNull(vm.state.value.editing)
    }

    @Test fun formatsTime() {
        assertEquals("01:01", formatTime(61_000))
        assertEquals("00:00", formatTime(-5))
    }
}
