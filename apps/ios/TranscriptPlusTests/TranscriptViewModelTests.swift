import Testing
@testable import TranscriptPlus

@MainActor
struct TranscriptViewModelTests {
    private func project() -> Project {
        Project(id: "p", title: "t", durationMs: 10_000, created: .now, status: .completed,
                segments: [Segment(id: "s", startMs: 0, endMs: 1000, text: "原文", speaker: "甲")])
    }

    @Test func commitEditTrimsAndSaves() {
        let vm = TranscriptViewModel(project: project())
        vm.beginEdit(vm.segments[0])
        vm.commitEdit(text: "  新文字 ")
        #expect(vm.segments[0].text == "新文字")
        #expect(vm.editing == nil)
    }

    @Test func emptyEditIsRejected() {
        let vm = TranscriptViewModel(project: project())
        vm.beginEdit(vm.segments[0])
        vm.commitEdit(text: "   ")
        #expect(vm.segments[0].text == "原文")
        #expect(vm.editing != nil)
    }

    @Test func formatTime() {
        #expect(TranscriptPlus.formatTime(ms: 61_000) == "01:01")
        #expect(TranscriptPlus.formatTime(ms: -5) == "00:00")
    }
}
