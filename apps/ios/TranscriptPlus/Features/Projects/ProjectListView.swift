import SwiftUI

struct ProjectListView: View {
    @State var viewModel: ProjectListViewModel
    @State private var pendingDelete: Project?

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("專案")
                .task { await viewModel.load() }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .loading:
            ProgressView()
        case .failed(let message):
            ContentUnavailableView("無法載入專案", systemImage: "exclamationmark.triangle", description: Text(message))
        case .loaded(let projects) where projects.isEmpty:
            ContentUnavailableView("還沒有專案", systemImage: "waveform",
                                   description: Text("錄音或匯入音訊，全程在這支手機上處理。"))
        case .loaded(let projects):
            List {
                ForEach(projects) { project in
                    NavigationLink(value: project) { ProjectRow(project: project) }
                        .swipeActions {
                            Button("刪除", role: .destructive) { pendingDelete = project }
                        }
                }
            }
            .navigationDestination(for: Project.self) { project in
                TranscriptView(viewModel: TranscriptViewModel(project: project))
            }
            .confirmationDialog("刪除這個專案？", isPresented: Binding(
                get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }
            ), presenting: pendingDelete) { project in
                Button("刪除「\(project.title)」及原始錄音", role: .destructive) {
                    Task { await viewModel.delete(project) }
                }
            } message: { _ in
                Text("會同時刪除手機上的原始錄音副本，無法復原。")
            }
        }
    }
}

extension Project: Hashable {
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

struct ProjectRow: View {
    let project: Project

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(project.title).font(.headline)
            HStack {
                Text(formatTime(ms: project.durationMs))
                Text("·")
                statusLabel
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }

    // Status is conveyed with an icon and text, never colour alone.
    @ViewBuilder
    private var statusLabel: some View {
        switch project.status {
        case .queued: Label("等待處理", systemImage: "clock")
        case .processing(let stage): Label(stage, systemImage: "waveform")
        case .completed: Label("已完成", systemImage: "checkmark.circle")
        case .failed(let message): Label(message, systemImage: "xmark.octagon")
        case .interrupted: Label("已中斷，可重試", systemImage: "exclamationmark.arrow.circlepath")
        }
    }
}
