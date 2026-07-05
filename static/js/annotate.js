let currentPair = null;
let isSaving = false;
let isProcessing = false;

// Debounce wrapper for button handlers
function setButtonLoading(btnId, isLoading) {
    const btn = document.getElementById(btnId);
    if (!btn) return;

    if (isLoading) {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = '⏳ ' + btn.textContent;
        btn.style.opacity = '0.6';
    } else {
        btn.disabled = false;
        btn.textContent = btn.dataset.originalText || btn.textContent;
        btn.style.opacity = '1';
    }
}

// Debounced handlers to prevent double-clicks
async function handleSave() {
    if (isProcessing) return;
    isProcessing = true;
    setButtonLoading('save-btn', true);
    try {
        await savePair();
    } finally {
        isProcessing = false;
        setButtonLoading('save-btn', false);
    }
}

async function handleSkip() {
    if (isProcessing) return;
    isProcessing = true;
    setButtonLoading('skip-btn', true);
    try {
        await skipPair();
    } finally {
        isProcessing = false;
        setButtonLoading('skip-btn', false);
    }
}

// Track unsaved changes and last pair
let lastPairId = null;
let hasUnsavedChanges = false;

// Draft persistence functions
function saveDrafts() {
    if (!currentPair) return;
    const drafts = {
        pair_id: currentPair.id,
        label: document.querySelector("input[name='label']:checked")?.value || '',
        quote: document.getElementById('quote').value,
        explanation: document.getElementById('explanation').value,
        timestamp: Date.now()
    };
    localStorage.setItem('annotation_draft', JSON.stringify(drafts));
}

function loadDrafts() {
    try {
        const saved = localStorage.getItem('annotation_draft');
        if (!saved || !currentPair) return;

        const drafts = JSON.parse(saved);
        // Only load drafts if they're for the current pair
        if (drafts.pair_id === currentPair.id) {
            if (drafts.label) {
                const labelEl = document.getElementById(`label-${drafts.label.toLowerCase().replace(/_/g, '-')}`);
                if (labelEl) labelEl.checked = true;
            }
            if (drafts.quote) document.getElementById('quote').value = drafts.quote;
            if (drafts.explanation) document.getElementById('explanation').value = drafts.explanation;
            markChanged();
        }
    } catch (error) {
        console.error('Error loading drafts:', error);
    }
}

function clearDrafts() {
    localStorage.removeItem('annotation_draft');
}

function markChanged() {
    hasUnsavedChanges = true;
}

function markSaved() {
    hasUnsavedChanges = false;
}

// Warn before leaving with unsaved changes
window.addEventListener('beforeunload', (e) => {
    const quote = document.getElementById('quote').value.trim();
    const explanation = document.getElementById('explanation').value.trim();
    if ((quote || explanation) && hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
});

// Intercept skip to warn about unsaved changes
async function skipWithWarning() {
    const quote = document.getElementById('quote').value.trim();
    const explanation = document.getElementById('explanation').value.trim();
    if ((quote || explanation) && hasUnsavedChanges) {
        if (!confirm('You have unsaved changes. Do you want to skip this pair and lose your changes?')) {
            return;
        }
    }
    clearDrafts();
    await handleSkip();
}

function goBackToLastPair() {
    if (!lastPairId) return;
    // Reload last pair without marking changes
    currentPair = null;
    fetch(`/api/pair/${lastPairId}`)
        .then(r => r.json())
        .then(pair => {
            currentPair = pair;
            renderPair(pair);
            clearForm();
        });
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
    loadNextPair();
    updateProgress();
    loadUserTarget();
    setupKeyboardShortcuts();

    // Track form changes and save drafts
    const quoteInput = document.getElementById('quote');
    const explanationInput = document.getElementById('explanation');

    quoteInput.addEventListener('input', () => {
        markChanged();
        saveDrafts();
    });

    explanationInput.addEventListener('input', () => {
        markChanged();
        saveDrafts();
    });

    document.querySelectorAll("input[name='label']").forEach(el => {
        el.addEventListener('change', () => {
            markChanged();
            saveDrafts();
        });
    });

    // Load saved drafts on page load
    loadDrafts();
});

function setupKeyboardShortcuts() {
    document.addEventListener("keydown", (e) => {
        // Don't trigger shortcuts if typing in a textarea
        if (e.target.tagName === "TEXTAREA") return;

        const labelMap = {
            "1": "TRUE",
            "2": "FALSE",
            "3": "MIXED",
            "4": "NO_SUFFICIENT_INFO",
            "5": "UNVERIFIABLE",
        };

        if (e.key in labelMap) {
            document.getElementById(`label-${labelMap[e.key].toLowerCase().replace(/_/g, "-")}`).checked = true;
        }
    });
}

async function loadNextPair() {
    try {
        // Store current pair as last before loading next
        if (currentPair) {
            lastPairId = currentPair.id;
            const goBackBtn = document.getElementById('go-back-btn');
            if (goBackBtn) goBackBtn.style.display = 'inline-block';
        }

        const endpoint = (typeof previewMode !== 'undefined' && previewMode) ? "/api/pair/preview" : "/api/pair/next";
        const response = await fetch(endpoint);
        const data = await response.json();

        if (!response.ok || data.status !== "ok") {
            if (data.status === "no_samples") {
                showStatus("info", "No samples available yet for preview");
            } else {
                showStatus(data.status || "error", data.error || "Failed to load next pair");
            }
            disableForm();
            return;
        }

        currentPair = data.pair;
        renderPair(currentPair);
        clearForm();
        markSaved();
        loadDrafts();

        // In preview mode, disable save/skip buttons
        if (typeof previewMode !== 'undefined' && previewMode) {
            document.querySelectorAll(".btn-group button").forEach(btn => {
                btn.disabled = true;
                btn.style.opacity = "0.5";
                btn.style.cursor = "not-allowed";
            });
        }
    } catch (error) {
        showStatus("error", `Error loading pair: ${error.message}`);
        disableForm();
    }
}

function renderPair(pair) {
    // Article title (prominent header)
    const articleTitle = pair.article_title || "Unknown Article";
    document.getElementById("articleLink").textContent = articleTitle;
    document.getElementById("articleLink").href = `https://en.wikipedia.org/wiki/${encodeURIComponent(articleTitle)}`;

    // Passage
    const passageEl = document.getElementById("passageText");
    passageEl.textContent = pair.passage_text || "No passage text";

    // Context with fact highlighting
    const contextEl = document.getElementById("contextContent");
    if (pair.passage_context) {
        const highlighted = highlightFacts(pair.passage_context);
        contextEl.innerHTML = `<div class="fact-check-note"><span>Passage to Fact Check Underlined in Red</span></div><pre>${highlighted}</pre>`;
        contextEl.classList.remove("empty-state");
    } else {
        contextEl.innerHTML = '<span class="empty-state">No context available</span>';
        contextEl.classList.add("empty-state");
    }

    // Citation
    document.getElementById("citationText").textContent = pair.citation_raw_text
        ? pair.citation_raw_text.substring(0, 10000)
        : "No citation text";

    // Metadata (removed article title from here since it's now in header)
    const citationMeta = [
        pair.citation_title,
        pair.citation_journal,
        pair.citation_year,
    ]
        .filter(Boolean)
        .join(" — ");
    document.getElementById("citationMeta").textContent = citationMeta || "—";

    // URL
    const urlEl = document.getElementById("citationUrl");
    if (pair.citation_source_url) {
        urlEl.href = pair.citation_source_url;
        try {
            const domain = new URL(pair.citation_source_url).hostname;
            urlEl.textContent = domain;
        } catch {
            urlEl.textContent = pair.citation_source_url.substring(0, 40);
        }
    } else {
        urlEl.textContent = "No URL";
        urlEl.href = "#";
        urlEl.style.pointerEvents = "none";
        urlEl.style.color = "#999";
    }
}

function highlightFacts(text) {
    // Find <fact>...</fact> markers and highlight the fact in bold red with underline
    const escaped = escapeHtml(text);
    return escaped.replace(
        /&lt;fact&gt;(.*?)&lt;\/fact&gt;/gs,
        '<span style="font-weight: bold; color: #dc2626; text-decoration: underline; background-color: #fee2e2; padding: 2px 4px; border-radius: 2px;">$1</span>'
    );
}

function clearForm() {
    document.querySelectorAll("input[name='label']").forEach((el) => (el.checked = false));
    document.getElementById("quote").value = "";
    document.getElementById("explanation").value = "";
    document.getElementById("quote").focus();
}

function disableForm() {
    document.querySelectorAll("#annotationForm input, #annotationForm textarea, #annotationForm button").forEach(
        (el) => (el.disabled = true)
    );
}

function validateForm() {
    const label = document.querySelector("input[name='label']:checked");
    const quote = document.getElementById("quote").value.trim();
    const explanation = document.getElementById("explanation").value.trim();
    const errors = [];

    if (!label) {
        errors.push("Please select a label");
    }

    if (!quote) {
        errors.push("Please provide a quote from the source");
    }

    if (!explanation) {
        errors.push("Please provide an explanation");
    }

    if (errors.length > 0) {
        showStatus("error", "⚠️ Please complete the form:\n" + errors.join("\n"));
        return false;
    }

    return true;
}

async function savePair() {
    if (isSaving) return;
    if (!currentPair) return;
    if (!validateForm()) return;

    isSaving = true;

    const label = document.querySelector("input[name='label']:checked").value;
    const quote = document.getElementById("quote").value.trim();
    const explanation = document.getElementById("explanation").value.trim();

    try {
        const response = await fetch("/api/annotation", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                pair_id: currentPair.id,
                label,
                quote,
                explanation,
            }),
        });

        if (!response.ok) {
            const data = await response.json();
            showStatus("error", data.error || "Failed to save annotation");
            return;
        }

        showStatus("success", "Annotation saved! Loading next pair...");
        clearDrafts();
        updateProgress();
        setTimeout(loadNextPair, 500);
    } catch (error) {
        showStatus("error", `Error saving: ${error.message}`);
    } finally {
        isSaving = false;
    }
}

async function skipPair() {
    if (!currentPair) return;

    try {
        const response = await fetch("/api/annotation/skip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pair_id: currentPair.id }),
        });

        if (!response.ok) {
            showStatus("error", "Failed to skip pair");
            return;
        }

        showStatus("info", "Pair skipped. Loading next...");
        updateProgress();
        setTimeout(loadNextPair, 500);
    } catch (error) {
        showStatus("error", `Error skipping: ${error.message}`);
    }
}

async function updateProgress() {
    try {
        const [progressRes, targetRes] = await Promise.all([
            fetch("/api/progress"),
            fetch("/api/user/target")
        ]);

        const data = await progressRes.json();
        const userData = await targetRes.json();

        const current = data.annotations_count || 0;
        const target = userData.annotation_target;

        let progressText = `${current} annotations`;
        let progressPercent = 0;

        if (target && target > 0) {
            progressPercent = Math.min(100, (current / target) * 100);
            progressText = `${current} / ${target}`;
            document.getElementById("target-info").textContent = `Your target: ${target} annotations`;
        } else if (data.max_annotations_cap && data.max_annotations_cap > 0) {
            const remaining = data.remaining_until_cap || 0;
            progressPercent = Math.min(100, ((current / data.max_annotations_cap) * 100));
            progressText = `${current} / ${data.max_annotations_cap}`;
            document.getElementById("target-info").textContent = `Cap: ${data.max_annotations_cap} annotations (${remaining} remaining)`;
        } else {
            document.getElementById("target-info").textContent = "No target set";
        }

        document.getElementById("progress-text").textContent = progressText;
        document.getElementById("progress-fill").style.width = progressPercent + "%";
    } catch (error) {
        console.error("Error updating progress:", error);
    }
}

async function loadUserTarget() {
    try {
        const response = await fetch("/api/user/target");
        const data = await response.json();
        if (data.annotation_target) {
            document.getElementById("targetInput").value = data.annotation_target;
        }
    } catch (error) {
        console.error("Error loading target:", error);
    }
}

function openTargetModal() {
    document.getElementById("targetModal").classList.remove("hidden");
    loadUserTarget();
}

function closeTargetModal() {
    document.getElementById("targetModal").classList.add("hidden");
}

async function saveTarget() {
    const target = document.getElementById("targetInput").value.trim();
    if (!target) {
        alert("Please enter a target");
        return;
    }

    try {
        const response = await fetch("/api/user/target", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target: parseInt(target) }),
        });

        if (!response.ok) {
            const data = await response.json();
            alert(data.error || "Failed to save target");
            return;
        }

        closeTargetModal();
        updateProgress();
        showStatus("success", "Target updated!");
    } catch (error) {
        alert("Error saving target: " + error.message);
    }
}

async function clearTarget() {
    if (!confirm("Clear your annotation target?")) {
        return;
    }

    try {
        const response = await fetch("/api/user/target", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target: null }),
        });

        if (!response.ok) {
            alert("Failed to clear target");
            return;
        }

        closeTargetModal();
        updateProgress();
        showStatus("success", "Target cleared!");
    } catch (error) {
        alert("Error clearing target: " + error.message);
    }
}

function showStatus(type, message) {
    const container = document.getElementById("status-container");
    const classes = {
        success: "status-success",
        error: "status-error",
        info: "status-info",
    };
    const className = classes[type] || "status-info";

    const el = document.createElement("div");
    el.className = `status-message ${className}`;
    el.textContent = message;
    container.innerHTML = "";
    container.appendChild(el);

    setTimeout(() => {
        if (container.contains(el)) {
            el.remove();
        }
    }, 5000);
}

function toggleCollapsible(event) {
    const header = event.currentTarget;
    const content = header.nextElementSibling;
    header.classList.toggle("open");
    content.classList.toggle("open");
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
