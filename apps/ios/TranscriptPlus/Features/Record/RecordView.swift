import SwiftUI

/// Placeholder. Recording (AVAudioRecorder, interruption handling, consent notice) lands in M2.
struct RecordView: View {
    var body: some View {
        NavigationStack {
            ContentUnavailableView("錄音", systemImage: "mic",
                                   description: Text("錄製他人聲音前，請先取得對方同意。錄音功能開發中。"))
                .navigationTitle("錄音")
        }
    }
}
