package com.transcriptplus.mobile.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.transcriptplus.mobile.R

private data class ModelInfo(val name: String, val purpose: String, val sizeMb: Int, val installed: Boolean)

// Static until the model manager exists (download, hash verify, delete).
private val models = listOf(
    ModelInfo("語音辨識（基本）", "轉錄", 150, false),
    ModelInfo("語音辨識（Breeze，高品質）", "轉錄", 890, false),
    ModelInfo("講者分辨", "講者", 40, false),
)

@Composable
fun SettingsScreen() {
    Column {
        models.forEach { model ->
            ListItem(
                headlineContent = { Text(model.name) },
                supportingContent = { Text("${model.purpose} · ${model.sizeMb} MB") },
                trailingContent = { Text(if (model.installed) "已安裝" else "未下載") },
            )
        }
        Text(
            stringResource(R.string.privacy_note),
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(16.dp),
        )
    }
}
