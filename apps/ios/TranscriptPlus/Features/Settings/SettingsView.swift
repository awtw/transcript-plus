import SwiftUI

struct ModelInfo: Identifiable {
    let id: String
    let name: String
    let purpose: String
    let sizeMB: Int
    let installed: Bool
}

struct SettingsView: View {
    // Static until the model manager exists (download, hash verify, delete).
    private let models = [
        ModelInfo(id: "asr-base", name: "語音辨識（基本）", purpose: "轉錄", sizeMB: 150, installed: false),
        ModelInfo(id: "asr-breeze", name: "語音辨識（Breeze，高品質）", purpose: "轉錄", sizeMB: 890, installed: false),
        ModelInfo(id: "speaker", name: "講者分辨", purpose: "講者", sizeMB: 40, installed: false),
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section("模型") {
                    ForEach(models) { model in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(model.name)
                                Text("\(model.purpose) · \(model.sizeMB) MB").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(model.installed ? "已安裝" : "未下載").foregroundStyle(.secondary)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
                Section("隱私") {
                    Text("所有轉錄都在這支手機上進行，錄音與逐字稿不會上傳。只有下載模型時需要網路。")
                        .font(.footnote)
                }
            }
            .navigationTitle("設定")
        }
    }
}
