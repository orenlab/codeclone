"use strict";

/** @type {any} */
const vscode = require("vscode");

const {emptyReviewArtifacts, treeAccessibilityInformation} = require("./formatters");

/**
 * @typedef {import("vscode").TreeDataProvider<any>} VSCodeTreeDataProvider
 * @typedef {import("vscode").CodeLensProvider} VSCodeCodeLensProvider
 * @typedef {import("vscode").FileDecorationProvider} VSCodeFileDecorationProvider
 */

class WorkspaceState {
    constructor(folder) {
        this.folder = folder;
        this.currentRunId = null;
        this.latestSummary = null;
        this.metricsSummary = null;
        this.latestTriage = null;
        this.changedSummary = null;
        this.analysisSettings = null;
        this.reviewed = [];
        this.lastScope = "workspace";
        this.lastUpdatedAt = null;
        this.groupCache = new Map();
        this.reviewArtifacts = emptyReviewArtifacts();
        this.gitSnapshot = null;
        this.stale = false;
        this.staleReason = null;
        this.lastStaleCheckAt = 0;
    }
}

class BaseTreeProvider {
    constructor(controller) {
        this.controller = controller;
        this.emitter = new vscode.EventEmitter();
        this.onDidChangeTreeData = this.emitter.event;
    }

    refresh() {
        this.emitter.fire(undefined);
    }

    dispose() {
        this.emitter.dispose();
    }
}

/** @implements {VSCodeTreeDataProvider} */
class OverviewTreeProvider extends BaseTreeProvider {
    async getTreeItem(node) {
        return this.controller.createTreeItem(node);
    }

    async getChildren(node) {
        return this.controller.getOverviewChildren(node);
    }
}

/** @implements {VSCodeTreeDataProvider} */
class HotspotsTreeProvider extends BaseTreeProvider {
    async getTreeItem(node) {
        return this.controller.createTreeItem(node);
    }

    async getChildren(node) {
        return this.controller.getHotspotsChildren(node);
    }
}

/** @implements {VSCodeTreeDataProvider} */
class SessionTreeProvider extends BaseTreeProvider {
    async getTreeItem(node) {
        return this.controller.createTreeItem(node);
    }

    async getChildren(node) {
        return this.controller.getSessionChildren(node);
    }
}

/** @implements {VSCodeCodeLensProvider} */
class ReviewCodeLensProvider {
    constructor(controller) {
        this.controller = controller;
        this.emitter = new vscode.EventEmitter();
        this.onDidChangeCodeLenses = this.emitter.event;
    }

    refresh() {
        this.emitter.fire(undefined);
    }

    provideCodeLenses(document) {
        return this.controller.provideReviewCodeLenses(document);
    }

    dispose() {
        this.emitter.dispose();
    }
}

/** @implements {VSCodeFileDecorationProvider} */
class ReviewFileDecorationProvider {
    constructor(controller) {
        this.controller = controller;
        this.emitter = new vscode.EventEmitter();
        this.onDidChangeFileDecorations = this.emitter.event;
    }

    refresh(uri) {
        this.emitter.fire(uri);
    }

    provideFileDecoration(uri) {
        return this.controller.provideFileDecoration(uri);
    }

    dispose() {
        this.emitter.dispose();
    }
}

module.exports = {
    HotspotsTreeProvider,
    OverviewTreeProvider,
    ReviewCodeLensProvider,
    ReviewFileDecorationProvider,
    SessionTreeProvider,
    WorkspaceState,
    treeAccessibilityInformation,
};
