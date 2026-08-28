package io.orenlab.codeclone.jetbrains.analysis

import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.isRegularFile

object CoverageXmlResolver {
    fun resolve(workspaceRoot: String, configuredPath: String, autoDetect: Boolean): String? {
        val root = Path.of(workspaceRoot).normalize().toAbsolutePath()
        val configured = configuredPath.trim()
        if (configured.isNotEmpty()) {
            val local = workspaceLocalPath(root, configured) ?: return null
            return toRepoRelativeMcpPath(root, local)
        }
        if (!autoDetect) {
            return null
        }
        val detected = workspaceLocalPath(root, "coverage.xml") ?: return null
        if (!detected.isRegularFile()) {
            return null
        }
        return toRepoRelativeMcpPath(root, detected)
    }

    private fun workspaceLocalPath(root: Path, candidate: String): Path? {
        val trimmed = candidate.trim()
        if (trimmed.isEmpty()) {
            return null
        }
        val resolved = if (Path.of(trimmed).isAbsolute) {
            Path.of(trimmed).normalize()
        } else {
            root.resolve(trimmed).normalize()
        }
        val relative = root.relativize(resolved)
        if (relative.startsWith("..") || relative.isAbsolute) {
            return null
        }
        return resolved
    }

    private fun toRepoRelativeMcpPath(root: Path, resolved: Path): String? {
        val relative = root.relativize(resolved.normalize())
        if (relative.startsWith("..") || relative.isAbsolute) {
            return null
        }
        return relative.toString().replace('\\', '/')
    }
}
