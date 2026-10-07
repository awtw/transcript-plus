import SwiftUI

struct TranscriptView: View {
    @State var viewModel: TranscriptViewModel

    var body: some View {
        Group {
            if viewModel.segments.isEmpty {
                ContentUnavailableView("尚無逐字稿", systemImage: "text.alignleft",
                                       description: Text("轉錄完成後會顯示在這裡。"))
            } else {
                List(viewModel.segments) { segment in
                    Button { viewModel.beginEdit(segment) } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(formatTime(ms: segment.startMs)) · \(segment.speaker)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(segment.text)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(formatTime(ms: segment.startMs))，\(segment.speaker)，\(segment.text)")
                    .accessibilityHint("點兩下編輯")
                }
            }
        }
        .navigationTitle(viewModel.project.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $viewModel.editing) { segment in
            EditSegmentSheet(segment: segment) { viewModel.commitEdit(text: $0) }
        }
    }
}

struct EditSegmentSheet: View {
    let segment: Segment
    let onSave: (String) -> Void
    @State private var text: String
    @Environment(\.dismiss) private var dismiss

    init(segment: Segment, onSave: @escaping (String) -> Void) {
        self.segment = segment
        self.onSave = onSave
        _text = State(initialValue: segment.text)
    }

    var body: some View {
        NavigationStack {
            Form { TextField("文字", text: $text, axis: .vertical).lineLimit(3...10) }
                .navigationTitle("編輯段落")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("完成") { onSave(text); dismiss() }
                            .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
        }
        .presentationDetents([.medium])
    }
}
