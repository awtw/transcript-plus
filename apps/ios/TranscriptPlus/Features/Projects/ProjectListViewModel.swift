import Foundation
import Observation

@MainActor
@Observable
final class ProjectListViewModel {
    enum State: Equatable {
        case loading
        case loaded([Project])
        case failed(String)
    }

    private(set) var state: State = .loading
    private let repository: ProjectRepository

    init(repository: ProjectRepository) {
        self.repository = repository
    }

    func load() async {
        do {
            state = .loaded(try await repository.projects())
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    func delete(_ project: Project) async {
        do {
            try await repository.delete(id: project.id)
            await load()
        } catch {
            state = .failed(error.localizedDescription)
        }
    }
}
