package io.orenlab.codeclone.jetbrains.memory

data class MemoryRecordItem(
    val id: String,
    val type: String,
    val status: String,
    val statement: String,
    val confidence: String?,
)

data class MemorySnapshot(
    val supported: Boolean = false,
    val connected: Boolean = false,
    val backend: String? = null,
    val recordCount: Int? = null,
    val draftCount: Int = 0,
    val activeCount: Int? = null,
    val staleCount: Int = 0,
    val drafts: List<MemoryRecordItem> = emptyList(),
    val stale: List<MemoryRecordItem> = emptyList(),
)
