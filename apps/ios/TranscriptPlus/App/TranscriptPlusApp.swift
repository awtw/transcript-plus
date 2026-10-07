import SwiftUI

@main
struct TranscriptPlusApp: App {
    // One repository for the whole app. Swap InMemoryProjectRepository for the Rust-core
    // backed implementation here; nothing else in the UI layer changes.
    private let repository: ProjectRepository = InMemoryProjectRepository.sample

    var body: some Scene {
        WindowGroup {
            RootView(repository: repository)
        }
    }
}

struct RootView: View {
    let repository: ProjectRepository

    var body: some View {
        TabView {
            ProjectListView(viewModel: ProjectListViewModel(repository: repository))
                .tabItem { Label("專案", systemImage: "doc.text") }
            RecordView()
                .tabItem { Label("錄音", systemImage: "mic.fill") }
            SettingsView()
                .tabItem { Label("設定", systemImage: "gearshape") }
        }
    }
}
