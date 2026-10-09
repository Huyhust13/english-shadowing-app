// Rich-text notes editor shared by the Shadowing and Practice pages, plus helpers to
// show saved notes safely. Standalone (no dependency on app.js), so a page can load it
// before its own inline script.
//
//   var ed = RichText.mount(document.getElementById("myEditor"), { placeholder: "…", label: "Notes" });
//   ed.get()          -> sanitised HTML ("" when empty)
//   ed.set(notes)     -> load saved notes (HTML or old plain text)
//   RichText.toHTML(notes)  -> safe HTML for display
//   RichText.toText(notes)  -> plain text, e.g. for a one-line preview
(function () {
  "use strict";

  // Notes are stored as HTML. Only these tags survive; every attribute is dropped.
  var ALLOWED_TAGS = { B: 1, STRONG: 1, I: 1, EM: 1, U: 1, S: 1, STRIKE: 1, MARK: 1, UL: 1, OL: 1, LI: 1, BR: 1, P: 1, DIV: 1 };
  var DROPPED_TAGS = { SCRIPT: 1, STYLE: 1, TEMPLATE: 1, IFRAME: 1, OBJECT: 1, EMBED: 1, NOSCRIPT: 1 };

  function sanitize(html) {
    var doc = new DOMParser().parseFromString("<body>" + html + "</body>", "text/html");
    var out = document.createElement("div");
    (function copy(src, dest) {
      src.childNodes.forEach(function (node) {
        if (node.nodeType === Node.TEXT_NODE) {
          dest.appendChild(document.createTextNode(node.nodeValue));
        } else if (node.nodeType === Node.ELEMENT_NODE && !DROPPED_TAGS[node.tagName]) {
          if (ALLOWED_TAGS[node.tagName]) {
            var el = document.createElement(node.tagName);
            dest.appendChild(el);
            copy(node, el);
          } else {
            copy(node, dest); // keep the text of unknown tags, drop the tag itself
          }
        }
      });
    })(doc.body, out);
    return out.innerHTML;
  }

  function isHTML(notes) { return /<\/?[a-z][^>]*>/i.test(notes); }

  // Older notes are plain text; newer ones are HTML from the editor.
  function toHTML(notes) {
    if (!notes) return "";
    if (isHTML(notes)) return sanitize(notes);
    var d = document.createElement("div");
    d.textContent = notes;
    return d.innerHTML.replace(/\n/g, "<br>");
  }

  function toText(notes) {
    if (!notes) return "";
    if (!isHTML(notes)) return notes.replace(/\s+/g, " ").trim();
    var doc = new DOMParser().parseFromString("<body>" + sanitize(notes.replace(/<\/?(br|p|div|li|ul|ol)\b[^>]*>/gi, " $&")) + "</body>", "text/html");
    return doc.body.textContent.replace(/\s+/g, " ").trim();
  }

  var TOOLBAR =
    '<div class="toolbar" role="toolbar" aria-label="Formatting">' +
    '<button type="button" class="tool-btn" data-cmd="bold" title="Bold (Ctrl+B)" aria-pressed="false"><b>B</b></button>' +
    '<button type="button" class="tool-btn" data-cmd="italic" title="Italic (Ctrl+I)" aria-pressed="false"><i>I</i></button>' +
    '<button type="button" class="tool-btn" data-cmd="underline" title="Underline (Ctrl+U)" aria-pressed="false"><u>U</u></button>' +
    '<button type="button" class="tool-btn" data-cmd="strikeThrough" title="Strikethrough" aria-pressed="false"><s>S</s></button>' +
    '<button type="button" class="tool-btn" data-cmd="highlight" title="Highlight (Ctrl+Shift+H)" aria-pressed="false"><mark class="tool-mark">H</mark></button>' +
    '<span class="sep" aria-hidden="true"></span>' +
    '<button type="button" class="tool-btn" data-cmd="insertUnorderedList" title="Bullet list" aria-pressed="false">• List</button>' +
    '<button type="button" class="tool-btn" data-cmd="insertOrderedList" title="Numbered list" aria-pressed="false">1. List</button>' +
    '<span class="sep" aria-hidden="true"></span>' +
    '<button type="button" class="tool-btn" data-cmd="removeFormat" title="Clear formatting">Clear</button>' +
    "</div>";

  function closestIn(node, tagName, root) {
    while (node && node !== root) {
      if (node.nodeName === tagName) return node;
      node = node.parentNode;
    }
    return null;
  }

  function unwrap(el) {
    var parent = el.parentNode;
    while (el.firstChild) parent.insertBefore(el.firstChild, el);
    parent.removeChild(el);
  }

  function selectionRangeIn(root) {
    var sel = window.getSelection();
    if (!sel.rangeCount) return null;
    var range = sel.getRangeAt(0);
    return root.contains(range.commonAncestorContainer) ? range : null;
  }

  // execCommand has no native <mark> support, so highlight is done by hand.
  function toggleHighlight(ed) {
    var range = selectionRangeIn(ed);
    if (!range) return;
    var mark = closestIn(range.commonAncestorContainer, "MARK", ed);
    if (mark) {
      unwrap(mark);
      return;
    }
    if (range.collapsed) return;
    var holder = document.createElement("div");
    holder.appendChild(range.cloneContents());
    holder.querySelectorAll("mark").forEach(unwrap);
    document.execCommand("insertHTML", false, "<mark>" + holder.innerHTML + "</mark>");
  }

  function clearFormatting(ed) {
    var range = selectionRangeIn(ed);
    document.execCommand("removeFormat");
    if (range) {
      ed.querySelectorAll("mark").forEach(function (m) {
        if (range.intersectsNode(m)) unwrap(m);
      });
    }
  }

  // Build the toolbar + editable area inside `host` (an empty element) and wire it up.
  function mount(host, opts) {
    opts = opts || {};
    host.classList.add("editor");
    host.innerHTML = TOOLBAR;
    var ed = document.createElement("div");
    ed.className = "notes-input rich is-empty";
    ed.contentEditable = "true";
    ed.setAttribute("role", "textbox");
    ed.setAttribute("aria-multiline", "true");
    if (opts.labelledBy) ed.setAttribute("aria-labelledby", opts.labelledBy);
    if (opts.placeholder) ed.setAttribute("data-placeholder", opts.placeholder);
    if (opts.minHeight) ed.style.minHeight = opts.minHeight;
    if (opts.id) ed.id = opts.id;
    host.appendChild(ed);

    var buttons = host.querySelectorAll(".tool-btn");
    try { document.execCommand("styleWithCSS", false, false); } catch (e) {}

    function updateEmpty() {
      ed.classList.toggle("is-empty", !ed.textContent.trim() && !ed.querySelector("li"));
    }

    function updateToolbar() {
      var sel = window.getSelection();
      var inside = sel.rangeCount > 0 && ed.contains(sel.anchorNode);
      buttons.forEach(function (btn) {
        var cmd = btn.getAttribute("data-cmd");
        if (cmd === "removeFormat") return;
        var on = false;
        if (inside) {
          on = cmd === "highlight" ? !!closestIn(sel.anchorNode, "MARK", ed) : document.queryCommandState(cmd);
        }
        btn.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }

    function run(cmd) {
      ed.focus();
      if (cmd === "highlight") toggleHighlight(ed);
      else if (cmd === "removeFormat") clearFormatting(ed);
      else document.execCommand(cmd);
      updateEmpty();
      updateToolbar();
      if (opts.onInput) opts.onInput();
    }

    buttons.forEach(function (btn) {
      btn.addEventListener("mousedown", function (e) { e.preventDefault(); }); // keep the text selection
      btn.addEventListener("click", function () { run(btn.getAttribute("data-cmd")); });
    });

    ed.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "h") {
        e.preventDefault();
        run("highlight");
      }
    });

    // Paste as plain text so text copied from web pages doesn't bring its styling along.
    ed.addEventListener("paste", function (e) {
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData("text/plain");
      document.execCommand("insertText", false, text);
    });

    ed.addEventListener("input", function () {
      updateEmpty();
      if (opts.onInput) opts.onInput();
    });
    document.addEventListener("selectionchange", updateToolbar);

    return {
      input: ed,
      get: function () { return ed.textContent.trim() ? sanitize(ed.innerHTML) : ""; },
      set: function (notes) { ed.innerHTML = toHTML(notes); updateEmpty(); },
      focus: function () { ed.focus(); }
    };
  }

  // Collapse long rendered notes and add a "Show more" button after them when needed.
  // Call after `notesEl` is in the document.
  function clamp(notesEl) {
    notesEl.classList.add("clamped");
    if (notesEl.scrollHeight <= notesEl.clientHeight + 2) {
      notesEl.classList.remove("clamped");
      return null;
    }
    var more = document.createElement("button");
    more.type = "button";
    more.className = "more-btn";
    more.textContent = "Show more";
    more.addEventListener("click", function () {
      var collapsed = notesEl.classList.toggle("clamped");
      more.textContent = collapsed ? "Show more" : "Show less";
    });
    notesEl.parentNode.insertBefore(more, notesEl.nextSibling);
    return more;
  }

  window.RichText = { sanitize: sanitize, toHTML: toHTML, toText: toText, mount: mount, clamp: clamp };
})();
