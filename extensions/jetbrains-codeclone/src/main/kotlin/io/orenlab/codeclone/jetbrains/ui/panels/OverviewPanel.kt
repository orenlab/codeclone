package io.orenlab.codeclone.jetbrains.ui.panels

import com.intellij.DynamicBundle
import com.intellij.icons.AllIcons
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.ui.ColoredTreeCellRenderer
import com.intellij.ui.ScrollPaneFactory
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.treeStructure.Tree
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.tree.TreeUtil
import io.orenlab.codeclone.jetbrains.analysis.AnalysisSettingsResolver
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService
import io.orenlab.codeclone.jetbrains.service.WorkspaceRunState
import io.orenlab.codeclone.jetbrains.settings.CodeCloneSettings
import io.orenlab.codeclone.jetbrains.toolwindow.CodeCloneToolWindowTab
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.Icon
import javax.swing.JComponent
import javax.swing.SwingUtilities
import javax.swing.KeyStroke
import javax.swing.tree.DefaultMutableTreeNode
import javax.swing.tree.DefaultTreeModel
import javax.swing.tree.TreePath

sealed interface OverviewTreeNode {
    data class Section(
        val title: String,
        val subtitle: String?,
        val icon: Icon,
    ) : OverviewTreeNode

    data class Detail(
        val label: String,
        val value: String,
    ) : OverviewTreeNode

    data class ActionNode(
        val title: String,
        val subtitle: String?,
        val icon: Icon,
        val action: OverviewAction,
    ) : OverviewTreeNode

    data object Root : OverviewTreeNode
}

enum class OverviewAction {
    OPEN_HOTSPOTS,
    OPEN_SESSION_STATS,
    OPEN_AUDIT_TRAIL,
    OPEN_MEMORY,
    OPEN_TRIAGE,
    OPEN_SETTINGS,
}

class OverviewPanel(
    private val service: CodeCloneProjectService,
    private val messages: DynamicBundle,
    private val onTab: (CodeCloneToolWindowTab) -> Unit,
    private val onAction: (OverviewAction) -> Unit,
) {
    private val rootNode = DefaultMutableTreeNode(OverviewTreeNode.Root)
    private val treeModel = DefaultTreeModel(rootNode)
    private val tree = Tree(treeModel).apply {
        isRootVisible = false
        showsRootHandles = true
        cellRenderer = OverviewTreeCellRenderer()
        border = JBUI.Borders.empty()
        addMouseListener(
            object : MouseAdapter() {
                override fun mouseClicked(event: MouseEvent) {
                    if (!SwingUtilities.isLeftMouseButton(event)) return
                    val path = getPathForLocation(event.x, event.y) ?: return
                    val node = path.lastPathComponent as? DefaultMutableTreeNode ?: return
                    if (node.userObject is OverviewTreeNode.ActionNode) {
                        activatePath(path, activateSection = false)
                    } else if (event.clickCount >= 2) {
                        activatePath(path, activateSection = true)
                    }
                }
            },
        )
        inputMap.put(KeyStroke.getKeyStroke("ENTER"), "activateSelected")
        actionMap.put("activateSelected", object : javax.swing.AbstractAction() {
            override fun actionPerformed(e: java.awt.event.ActionEvent?) {
                activateSelectedNode()
            }
        })
    }

    private fun activateSelectedNode() {
        val path = tree.selectionPath ?: return
        activatePath(path, activateSection = true)
    }

    private fun activatePath(path: TreePath, activateSection: Boolean) {
        val node = path.lastPathComponent as? DefaultMutableTreeNode ?: return
        when (val payload = node.userObject) {
            is OverviewTreeNode.ActionNode -> onAction(payload.action)
            is OverviewTreeNode.Section -> {
                if (!activateSection) return
                val firstAction = firstActionChild(node)
                if (firstAction != null) {
                    onAction(firstAction.action)
                }
            }
            else -> Unit
        }
    }

    private fun firstActionChild(section: DefaultMutableTreeNode): OverviewTreeNode.ActionNode? {
        for (index in 0 until section.childCount) {
            val child = section.getChildAt(index) as? DefaultMutableTreeNode ?: continue
            val payload = child.userObject
            if (payload is OverviewTreeNode.ActionNode) {
                return payload
            }
        }
        return null
    }
    private val scrollPane = ScrollPaneFactory.createScrollPane(tree, true)

    init {
        render(service.state.value)
    }

    fun component(): JComponent = scrollPane

    fun render(state: WorkspaceRunState) {
        try {
            rootNode.removeAllChildren()
            populateTree(state, rootNode)
            treeModel.reload()
            ApplicationManager.getApplication().invokeLater {
                runCatching { TreeUtil.expandAll(tree) }
                if (tree.selectionPath == null && rootNode.childCount > 0) {
                    val first = rootNode.getChildAt(0)
                    tree.selectionPath = TreePath(arrayOf(rootNode, first))
                }
            }
        } catch (error: Throwable) {
            LOG.warn("CodeClone overview tree render failed", error)
        }
    }

    private fun populateTree(state: WorkspaceRunState, root: DefaultMutableTreeNode) {
        val connected = state.connectionSummary != "disconnected"
        val hasRun = state.runId != null
        val memory = state.memory
        val insights = state.sessionInsights
        val triage = state.triage
        val inventory = state.runSummary?.get("inventory")?.jsonObject
            ?: state.summary?.get("inventory")?.jsonObject

        addSection(
            root,
            messages.getMessage("overview.section.connection"),
            connectionSubtitle(state.connectionSummary),
            AllIcons.Nodes.Plugin,
            listOf(
                OverviewTreeNode.Detail(messages.getMessage("overview.field.status"), connectionLabel(state.connectionSummary)),
            ),
        )

        val settings = CodeCloneSettings.getInstance().config
        val analysis = AnalysisSettingsResolver.resolve(settings)
        val coverageSummary = when {
            settings.coverageXml.isNotBlank() -> settings.coverageXml
            settings.autoDetectCoverageXml -> messages.getMessage("overview.analysis.coverage.auto")
            else -> messages.getMessage("overview.analysis.coverage.off")
        }
        addSection(
            root,
            messages.getMessage("overview.section.analysis"),
            analysis.label,
            AllIcons.General.Settings,
            listOf(
                OverviewTreeNode.Detail(messages.getMessage("overview.field.analysis_profile"), analysis.label),
                OverviewTreeNode.Detail(messages.getMessage("overview.field.coverage"), coverageSummary),
                OverviewTreeNode.ActionNode(
                    messages.getMessage("action.settings"),
                    messages.getMessage("overview.action.settings.hint"),
                    AllIcons.General.Settings,
                    OverviewAction.OPEN_SETTINGS,
                ),
            ),
        )

        if (hasRun) {
            val healthChildren = buildList {
                add(OverviewTreeNode.Detail(messages.getMessage("overview.field.score"), "${state.healthScore ?: "—"}/${state.healthGrade ?: "—"}"))
                add(OverviewTreeNode.Detail(messages.getMessage("overview.field.run"), state.runId ?: "—"))
                add(OverviewTreeNode.Detail(messages.getMessage("overview.field.scope"), state.lastScope))
                inventory?.get("files")?.jsonPrimitive?.content?.let { files ->
                    add(OverviewTreeNode.Detail(messages.getMessage("overview.field.files"), files))
                }
                triage?.get("headline")?.jsonPrimitive?.content?.let { headline ->
                    add(OverviewTreeNode.Detail(messages.getMessage("overview.field.triage"), headline))
                }
                triage?.get("next_action")?.jsonPrimitive?.content?.let { action ->
                    add(OverviewTreeNode.Detail(messages.getMessage("overview.field.next_action"), action))
                }
                add(
                    OverviewTreeNode.ActionNode(
                        messages.getMessage("action.triage"),
                        messages.getMessage("overview.action.triage.hint"),
                        AllIcons.Toolwindows.ToolWindowStructure,
                        OverviewAction.OPEN_TRIAGE,
                    ),
                )
            }
            addSection(
                root,
                messages.getMessage("overview.section.health"),
                "${state.healthScore ?: "—"}/${state.healthGrade ?: "—"}",
                AllIcons.Nodes.Favorite,
                healthChildren,
            )

            addSection(
                root,
                messages.getMessage("overview.section.review"),
                messages.getMessage(
                    "overview.section.review.subtitle",
                    state.hotspots.size,
                    state.changedFindings.size,
                    state.reviewedFindingIds.size,
                ),
                AllIcons.Toolwindows.ToolWindowStructure,
                listOf(
                    OverviewTreeNode.Detail(messages.getMessage("overview.field.hotspots"), state.hotspots.size.toString()),
                    OverviewTreeNode.Detail(messages.getMessage("overview.field.changed"), state.changedFindings.size.toString()),
                    OverviewTreeNode.Detail(messages.getMessage("overview.field.reviewed"), state.reviewedFindingIds.size.toString()),
                    OverviewTreeNode.ActionNode(
                        messages.getMessage("tab.hotspots"),
                        messages.getMessage("overview.action.hotspots.hint"),
                        AllIcons.Actions.ListFiles,
                        OverviewAction.OPEN_HOTSPOTS,
                    ),
                ),
            )
        } else if (connected) {
            addSection(
                root,
                messages.getMessage("overview.section.run"),
                messages.getMessage("overview.section.run.pending"),
                AllIcons.Actions.Execute,
                listOf(
                    OverviewTreeNode.Detail(
                        messages.getMessage("overview.field.hint"),
                        messages.getMessage("overview.hint.connected"),
                    ),
                ),
            )
        }

        if (memory.supported) {
            val memoryChildren = buildList {
                add(OverviewTreeNode.Detail(messages.getMessage("overview.field.backend"), memory.backend ?: "unknown"))
                add(
                    OverviewTreeNode.Detail(
                        messages.getMessage("overview.field.records"),
                        buildString {
                            append("${messages.getMessage("overview.field.drafts")} ${memory.draftCount}")
                            memory.activeCount?.let { append(" · ${messages.getMessage("overview.field.active")} $it") }
                            append(" · ${messages.getMessage("overview.field.stale")} ${memory.staleCount}")
                        },
                    ),
                )
                if (connected) {
                    add(
                        OverviewTreeNode.ActionNode(
                            messages.getMessage("tab.memory"),
                            messages.getMessage("overview.action.memory.hint"),
                            AllIcons.Nodes.Module,
                            OverviewAction.OPEN_MEMORY,
                        ),
                    )
                }
            }
            addSection(
                root,
                messages.getMessage("overview.section.memory"),
                "${memory.draftCount} ${messages.getMessage("overview.field.drafts").lowercase()}",
                AllIcons.Nodes.Module,
                memoryChildren,
            )
        }

        if (insights.supported) {
            addSection(
                root,
                messages.getMessage("overview.section.session"),
                "${insights.liveAgents} agents · ${insights.activeIntents} intents",
                AllIcons.Actions.Preview,
                listOf(
                    OverviewTreeNode.Detail(messages.getMessage("overview.field.workspace_health"), insights.workspaceHealth ?: "unknown"),
                    OverviewTreeNode.Detail(messages.getMessage("overview.field.audit"), if (insights.auditEnabled) "on" else "off"),
                    OverviewTreeNode.ActionNode(
                        messages.getMessage("action.session.stats"),
                        messages.getMessage("overview.action.session.hint"),
                        AllIcons.Nodes.Module,
                        OverviewAction.OPEN_SESSION_STATS,
                    ),
                    OverviewTreeNode.ActionNode(
                        messages.getMessage("action.audit.trail"),
                        messages.getMessage("overview.action.audit.hint"),
                        AllIcons.Actions.Preview,
                        OverviewAction.OPEN_AUDIT_TRAIL,
                    ),
                ),
            )
        }

        if (!connected) {
            addSection(
                root,
                messages.getMessage("overview.section.getting_started"),
                messages.getMessage("overview.hint.disconnected"),
                AllIcons.General.Information,
                listOf(
                    OverviewTreeNode.Detail(
                        messages.getMessage("overview.field.hint"),
                        messages.getMessage("overview.hint.disconnected"),
                    ),
                ),
            )
        }
    }

    private fun addSection(
        root: DefaultMutableTreeNode,
        title: String,
        subtitle: String?,
        icon: Icon,
        children: List<OverviewTreeNode>,
    ) {
        val section = DefaultMutableTreeNode(OverviewTreeNode.Section(title, subtitle, icon))
        for (child in children) {
            section.add(DefaultMutableTreeNode(child))
        }
        root.add(section)
    }

    private fun connectionLabel(summary: String): String = when (summary) {
        "ready" -> messages.getMessage("overview.connection.ready")
        "connected" -> messages.getMessage("overview.connection.connected")
        "analyzing" -> messages.getMessage("overview.connection.analyzing")
        else -> messages.getMessage("overview.connection.disconnected")
    }

    private fun connectionSubtitle(summary: String): String = connectionLabel(summary)

    private class OverviewTreeCellRenderer : ColoredTreeCellRenderer() {
        override fun customizeCellRenderer(
            tree: javax.swing.JTree,
            value: Any?,
            selected: Boolean,
            expanded: Boolean,
            leaf: Boolean,
            row: Int,
            hasFocus: Boolean,
        ) {
            val node = (value as? DefaultMutableTreeNode)?.userObject as? OverviewTreeNode ?: return
            when (node) {
                is OverviewTreeNode.Section -> {
                    icon = node.icon
                    append(node.title, SimpleTextAttributes.REGULAR_BOLD_ATTRIBUTES)
                    node.subtitle?.let { append("  $it", SimpleTextAttributes.GRAYED_ATTRIBUTES) }
                }
                is OverviewTreeNode.Detail -> {
                    icon = null
                    append("${node.label}: ", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                    append(node.value, SimpleTextAttributes.REGULAR_ATTRIBUTES)
                }
                is OverviewTreeNode.ActionNode -> {
                    icon = node.icon
                    append(node.title, SimpleTextAttributes.REGULAR_ATTRIBUTES)
                    node.subtitle?.let { append("  $it", SimpleTextAttributes.GRAYED_ATTRIBUTES) }
                }
                OverviewTreeNode.Root -> Unit
            }
        }
    }

    companion object {
        private val LOG = Logger.getInstance(OverviewPanel::class.java)
    }
}
