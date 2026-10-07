import Foundation
import Observation

@MainActor
@Observable
final class TranscriptViewModel {
    let project: Project
    private(set) var segments: [Segment]
    var editing: Segment?

    init(project: Project) {
        self.project = project
        self.segments = project.segments
    }

    func beginEdit(_ segment: Segment) { editing = segment }

    /// Empty text is rejected, matching the core's INVALID_DOCUMENT rule.
    func commitEdit(text: String) {
        guard var segment = editing, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let index = segments.firstIndex(where: { $0.id == segment.id }) else { return }
        segment.text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        segments[index] = segment
        editing = nil
    }
}
