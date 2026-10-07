import Foundation

/// The UI's only dependency on data. The Rust core (via UniFFI) will provide the real implementation.
protocol ProjectRepository: Sendable {
    func projects() async throws -> [Project]
    func project(id: String) async throws -> Project
    func delete(id: String) async throws
}

enum RepositoryError: Error { case notFound }

actor InMemoryProjectStore {
    var items: [Project]
    init(_ items: [Project]) { self.items = items }
    func all() -> [Project] { items }
    func find(_ id: String) -> Project? { items.first { $0.id == id } }
    func remove(_ id: String) { items.removeAll { $0.id == id } }
}

struct InMemoryProjectRepository: ProjectRepository {
    private let store: InMemoryProjectStore
    init(items: [Project]) { store = InMemoryProjectStore(items) }

    func projects() async throws -> [Project] { await store.all() }
    func project(id: String) async throws -> Project {
        guard let project = await store.find(id) else { throw RepositoryError.notFound }
        return project
    }
    func delete(id: String) async throws { await store.remove(id) }

    static let sample = InMemoryProjectRepository(items: [
        Project(id: "p1", title: "週會錄音", durationMs: 1_800_000, created: .now, status: .completed, segments: [
            Segment(id: "s1", startMs: 1_200, endMs: 4_600, text: "我們下週三要把新版本上線。", speaker: "小王"),
            Segment(id: "s2", startMs: 5_000, endMs: 8_400, text: "測試報告什麼時候可以給我？", speaker: "小李"),
        ]),
        Project(id: "p2", title: "客戶訪談", durationMs: 2_700_000, created: .now.addingTimeInterval(-86_400),
                status: .processing(stage: "正在轉錄"), segments: []),
        Project(id: "p3", title: "語音備忘", durationMs: 95_000, created: .now.addingTimeInterval(-172_800),
                status: .interrupted, segments: []),
    ])
}
