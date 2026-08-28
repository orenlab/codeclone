#!/usr/bin/env bash
# Run the plugin sandbox IDE with a Gradle-compatible JDK (21).
#
# Gradle 8.12 + Kotlin 2.1 fail during settings evaluation when the launcher JVM
# is JDK 25+ (error message is only the Java version, e.g. "26.0.1"). IntelliJ
# Platform plugins still target Java 21 bytecode.
set -euo pipefail

cd "$(dirname "$0")"

resolve_java_home() {
    if [[ -n "${JAVA_HOME:-}" ]]; then
        local version
        version="$("$JAVA_HOME/bin/java" -version 2>&1 | head -n1 | sed -E 's/.*"([0-9]+).*/\1/')"
        if [[ "$version" == "21" ]]; then
            echo "$JAVA_HOME"
            return 0
        fi
    fi

    if command -v /usr/libexec/java_home >/dev/null 2>&1; then
        if /usr/libexec/java_home -v 21 >/dev/null 2>&1; then
            /usr/libexec/java_home -v 21
            return 0
        fi
    fi

    for candidate in \
        "${SDKMAN_DIR:-$HOME/.sdkman}/candidates/java/21."* \
        "/Applications/IntelliJ IDEA.app/Contents/jbr/Contents/Home" \
        "/Applications/IntelliJ IDEA CE.app/Contents/jbr/Contents/Home" \
        "/Applications/PyCharm.app/Contents/jbr/Contents/Home" \
        "/Applications/PyCharm CE.app/Contents/jbr/Contents/Home" \
        "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home" \
        "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"; do
        if [[ -x "$candidate/bin/java" ]]; then
            local version
            version="$("$candidate/bin/java" -version 2>&1 | head -n1 | sed -E 's/.*"([0-9]+).*/\1/')"
            if [[ "$version" == "21" ]]; then
                echo "$candidate"
                return 0
            fi
        fi
    done

    return 1
}

if ! JAVA_HOME="$(resolve_java_home)"; then
    cat >&2 <<'EOF'
CodeClone JetBrains plugin requires JDK 21 for Gradle.

Your default `java` is likely JDK 25+ which Gradle 8.12 cannot use as the launcher JVM
(failure message is only the version number, e.g. "26.0.1").

Install JDK 21, then either:
  export JAVA_HOME=$(/usr/libexec/java_home -v 21)   # macOS
  brew install openjdk@21

If PyCharm or IntelliJ is installed, this script also checks the bundled JBR
(usually Java 21) under /Applications/*.app/Contents/jbr.
EOF
    exit 1
fi

export JAVA_HOME
exec ./gradlew runIde "$@"
