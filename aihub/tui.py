"""
AIHub TUI Module (v0.1.4)
Full-screen Textual application — chat/agentic models only.
Features: hardware-aware model browser, installed-first sorting, capability badges,
category filters (Small/Medium/Large/XLarge), search by name or capability.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional
from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import Header, Footer, ListView, ListItem, Label, Input, Button, Static, Markdown, TextArea
from textual.containers import Vertical, Horizontal, Container, ScrollableContainer
from textual.binding import Binding
from textual.reactive import reactive
from textual import work
from rich.panel import Panel

from .config import config, HISTORY_DIR
from .ollama_client import get_local_model_sizes, get_model_info, chat_stream, is_ollama_running, unload_model
from .cli import load_registry_models, score_hardware
from .hardware import get_available_ram_gb
from .memory import load_memory, save_memory, get_memory_path, update_memory_entry, clear_memory, build_system_prompt
from .history import list_sessions, load_session as load_chat_session, save_session
from .models import categorize_model, get_capability_badges, get_speed_label, get_speed_color, sort_models_for_hardware


class ModelListItem(ListItem):
    """A list item representing a model card in the browser (v0.1.4)."""

    def __init__(self, model_data: dict, installed: bool, hw_compatible: bool,
                 context_size: str = "?", **kwargs):
        super().__init__(**kwargs)
        self.model_data   = model_data
        self.installed    = installed
        self.hw_compatible = hw_compatible
        self.context_size = context_size

    def compose(self):
        m        = self.model_data
        name     = m.get("name", "Unknown")
        vram     = m.get("vram_required", 0)
        size_gb  = m.get("size_gb", vram)
        is_api   = m.get("url", "").startswith("api://")
        speed    = get_speed_label(m)
        badges   = get_capability_badges(m, max_badges=4)
        use_case = ", ".join(m.get("use_cases", [])[:2])
        ctx_win  = m.get("context_window", 0)
        ctx_str  = self.context_size if self.context_size != "?" else (
            f"{ctx_win // 1024}k" if ctx_win else "?"
        )

        if self.installed:
            name_markup  = f"[bold green]{name}[/bold green]"
            status_badge = "[bold green]\u25cf INSTALLED[/bold green]"
        elif not self.hw_compatible and not is_api:
            name_markup  = f"[dim]{name}[/dim]"
            status_badge = "[dim]⚠ Exceeds HW[/dim]"
        else:
            name_markup  = f"[bold white]{name}[/bold white]"
            status_badge = "[dim cyan]Available[/dim cyan]"

        ram_str = "Cloud API" if is_api else f"{vram} GB RAM"
        size_str = "" if is_api else f" | {size_gb:.1f} GB"

        badge_markup = "  ".join(f"[dim cyan]{b}[/dim cyan]" for b in badges) if badges else ""

        yield Vertical(
            Horizontal(
                Label(name_markup, classes="model-name"),
                Label(f"  {status_badge}", classes="status-badge"),
                classes="model-header"
            ),
            Label(
                f"[dim]{ram_str}{size_str}  |  {speed}  |  Ctx: {ctx_str}[/dim]",
                classes="model-meta"
            ),
            Label(badge_markup, classes="model-badges"),
            Label(f"[dim]{use_case}[/dim]", classes="model-usecase"),
            classes="model-item"
        )


CAT_FILTER_OPTIONS = [
    ("Recommended", "recommended"),
    ("All",    "all"),
    ("Small",  "small"),
    ("Medium", "medium"),
    ("Large",  "large"),
    ("XLarge", "xlarge"),
]


class BrowserScreen(Screen):
    """Hardware-aware model browser screen (v0.1.4)."""

    BINDINGS = [
        Binding("q", "quit", "Quit",    show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("m", "memory", "Memory",  show=True),
        Binding("h", "history", "History", show=True),
    ]

    _active_category: str = "all"

    def compose(self):
        yield Header()
        yield Horizontal(
            Input(
                placeholder="Search by name, capability, use case...",
                id="search-input"
            ),
            Button("Refresh", id="refresh-btn", variant="primary"),
            classes="search-bar"
        )
        # Category filter buttons
        yield Horizontal(
            *[
                Button(label, id=f"cat-{val}", variant="default", classes="cat-btn")
                for label, val in CAT_FILTER_OPTIONS
            ],
            id="cat-filter-bar"
        )
        yield Static("", id="hw-info-bar", classes="hw-info")
        yield ListView(id="model-list")
        yield Footer()

    def on_mount(self) -> None:
        self._active_category = "recommended"
        self.refresh_models()

    def refresh_models(self) -> None:
        """Reload models from registry and Ollama, apply hardware-aware sorting."""
        list_view  = self.query_one("#model-list", ListView)
        list_view.clear()

        hw_ram     = get_available_ram_gb()
        registry   = load_registry_models()
        local_sizes = get_local_model_sizes()
        local_names = set(local_sizes.keys())

        # Update hw info bar
        hw_bar = self.query_one("#hw-info-bar", Static)
        hw_bar.update(
            f"[dim]Hardware limit:[/dim] [bold cyan]{hw_ram:.1f} GB[/bold cyan]  "
            f"[dim]|[/dim]  [green]\u25cf[/green] [dim]Installed[/dim]  "
            f"[cyan]\u2714[/cyan] [dim]Compatible[/dim]  "
            f"[dim]\u2718 Exceeds hardware[/dim]"
        )

        # Category filter
        cat_max = {"small": 4, "medium": 8, "large": 16, "xlarge": 99999}
        cat_min = {"small": 0, "medium": 4, "large":  8, "xlarge":    16}
        if self._active_category == "recommended":
            registry = [
                m for m in registry
                if m.get("vram_required", 0) <= hw_ram
                or m.get("vram_required", 0) == 0
            ]
        elif self._active_category != "all":
            cmin = cat_min[self._active_category]
            cmax = cat_max[self._active_category]
            registry = [
                m for m in registry
                if cmin < m.get("vram_required", 0) <= cmax
                or (self._active_category == "small" and m.get("vram_required", 0) == 0)
            ]

        # Search filter (applied on top of category)
        term = self.query_one("#search-input", Input).value.lower().strip()
        if term:
            registry = [
                m for m in registry
                if term in m.get("name", "").lower()
                or any(term in c.lower() for c in m.get("capabilities", []))
                or any(term in t.lower() for t in m.get("tags", []))
                or any(term in u.lower() for u in m.get("use_cases", []))
            ]

        # Split into installed / compatible / incompatible
        installed_models = [m for m in registry if m["name"] in local_names]
        not_installed    = [m for m in registry if m["name"] not in local_names]
        compatible, incompatible = sort_models_for_hardware(not_installed, hw_ram)

        def _add_item(m: dict, inst: bool, compat: bool):
            ctx = "?"
            if inst:
                info = get_model_info(m["name"])
                ctx  = str(info.get("context_length", "?"))
                if ctx != "?":
                    try:
                        ctx = f"{int(ctx) // 1024}k"
                    except Exception:
                        pass
            item = ModelListItem(m, inst, compat, ctx)
            if inst:
                item.add_class("installed")
            elif not compat and not m.get("url", "").startswith("api://"):
                item.add_class("incompatible")
            list_view.append(item)

        for m in sorted(installed_models, key=lambda x: x.get("vram_required", 0), reverse=True):
            _add_item(m, True, True)
        for m in compatible:
            _add_item(m, False, True)
        for m in incompatible:
            _add_item(m, False, False)

    def action_refresh(self) -> None:
        self.refresh_models()

    def action_memory(self) -> None:
        self.app.push_screen(MemoryScreen())

    def action_history(self) -> None:
        self.app.push_screen(HistorySelectScreen())

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Search models by name, capability, tag, or use case."""
        self.refresh_models()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "refresh-btn":
            self.refresh_models()
            return
        # Category filter buttons
        for _, val in CAT_FILTER_OPTIONS:
            if btn_id == f"cat-{val}":
                self._active_category = val
                # Highlight active button
                for label, v in CAT_FILTER_OPTIONS:
                    btn = self.query_one(f"#cat-{v}", Button)
                    if v == val:
                        btn.variant = "primary"
                    else:
                        btn.variant = "default"
                self.refresh_models()
                return

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ModelListItem):
            model_name = item.model_data["name"]
            if item.installed:
                def check_ctx(ctx_len: Optional[int]):
                    if ctx_len is not None:
                        self.app.push_screen(ChatScreen(model_name, context_length=ctx_len))
                self.app.push_screen(ContextConfigModal(model_name), check_ctx)
            else:
                self.app.push_screen(ModelDetailScreen(item.model_data))


class HardwareDiagnosticScreen(Screen):
    def compose(self):
        yield Vertical(
            Label("Hardware Diagnostics", id="main-title"),
            Label("Not fully interactive in TUI yet. Please use 'aihub hardware-scan' from CLI.", id="main-desc"),
            Button("← Back", id="back-btn", variant="primary"),
            classes="main-menu-container"
        )
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()


class ConfigScreen(Screen):
    def compose(self):
        yield Vertical(
            Label("Configuration", id="main-title"),
            Label("Config editor not fully interactive in TUI yet. Please use 'aihub config' from CLI.", id="main-desc"),
            Button("← Back", id="back-btn", variant="primary"),
            classes="main-menu-container"
        )
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()


class MainMenuScreen(Screen):
    """Main Menu Screen."""
    def compose(self):
        yield Vertical(
            Label("[bold #7c3aed]AIHub 0.1.4[/bold #7c3aed]", id="main-title"),
            Label("[dim]Your all-in-one local AI platform[/dim]", id="main-desc"),
            Button("🤖 Browse & Manage Models", id="btn-models", variant="primary"),
            Button("📚 Chat History",           id="btn-history", variant="default"),
            Button("🧠 Memory Management",      id="btn-memory", variant="default"),
            Button("🖥️  Hardware Diagnostics",  id="btn-hardware", variant="default"),
            Button("⚙️  Configuration",         id="btn-config", variant="default"),
            Button("🚪 Exit",                   id="btn-exit", variant="error"),
            classes="main-menu-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-models":
            self.app.push_screen(BrowserScreen())
        elif btn_id == "btn-history":
            self.app.push_screen(HistorySelectScreen())
        elif btn_id == "btn-memory":
            self.app.push_screen(MemoryScreen())
        elif btn_id == "btn-hardware":
            self.app.push_screen(HardwareDiagnosticScreen())
        elif btn_id == "btn-config":
            self.app.push_screen(ConfigScreen())
        elif btn_id == "btn-exit":
            self.app.exit()


class ContextConfigModal(ModalScreen[int]):
    """Modal to select context length before starting chat."""
    
    def __init__(self, model_name: str, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.default_ctx = config.default_context_length
        
    def compose(self) -> ComposeResult:
        from .hardware import estimate_kv_cache_gb
        est_gb = estimate_kv_cache_gb(self.default_ctx, self.model_name)
        
        yield Vertical(
            Label(f"[bold cyan]Chat Configuration: {self.model_name}[/bold cyan]"),
            Label("Enter Context Length (tokens):"),
            Input(placeholder=str(self.default_ctx), id="ctx-input", value=str(self.default_ctx)),
            Label(f"Estimated KV Cache: [bold green]~{est_gb}GB[/bold green]", id="est-label"),
            Horizontal(
                Button("Start Chat", id="start-btn", variant="primary"),
                Button("Cancel", id="cancel-btn", variant="default"),
                classes="modal-actions"
            ),
            classes="modal-container"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        try:
            val = int(event.value)
            from .hardware import estimate_kv_cache_gb
            est_gb = estimate_kv_cache_gb(val, self.model_name)
            self.query_one("#est-label", Label).update(f"Estimated KV Cache: [bold green]~{est_gb}GB[/bold green]")
        except:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            try:
                val = int(self.query_one("#ctx-input", Input).value)
                self.dismiss(val)
            except:
                self.dismiss(self.default_ctx)
        else:
            self.dismiss(None)


class ModelDetailScreen(Screen):
    """Model details and actions screen (v0.1.4 — chat/agentic only)."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self, model_data: dict, **kwargs):
        super().__init__(**kwargs)
        self.model_data = model_data

    def compose(self):
        m        = self.model_data
        name     = m.get("name", "?")
        desc     = m.get("description", "No description.")
        vram     = m.get("vram_required", 0)
        size_gb  = m.get("size_gb", vram)
        ctx_win  = m.get("context_window", 0)
        is_api   = m.get("url", "").startswith("api://")
        speed    = get_speed_label(m)
        badges   = get_capability_badges(m)
        use_cases = ", ".join(m.get("use_cases", []))
        category = m.get("category", "General")

        ram_str  = "Cloud API" if is_api else f"{vram} GB RAM"
        size_str = "N/A" if is_api else f"{size_gb:.1f} GB"
        ctx_str  = f"{ctx_win // 1024}k" if ctx_win else "?"
        badge_list = "  ".join(badges) if badges else "No specific badges"

        yield Header()
        yield Vertical(
            Label(f"[bold white]{name}[/bold white]", classes="title"),
            Label(f"[dim]{desc}[/dim]",               classes="desc"),
            Label(f"RAM: [cyan]{ram_str}[/cyan]  |  Size: [cyan]{size_str}[/cyan]  |  "
                  f"Context: [cyan]{ctx_str}[/cyan]  |  Speed: [green]{speed}[/green]"),
            Label(f"Category: [bold cyan]{category}[/bold cyan]"),
            Label(badge_list, classes="badges"),
            Label(f"[dim]Use cases:[/dim] [#a78bfa]{use_cases}[/#a78bfa]"),
            Horizontal(
                Button("Download (via Ollama)", id="download", variant="success"),
                Button("Back", id="back", variant="default"),
                classes="actions"
            ),
            classes="detail-panel"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "download":
            self.app.notify(
                f"Run in terminal: aihub models-download {self.model_data['name']}",
                severity="warning"
            )


class MemoryScreen(Screen):
    """Global and per-model memory editor."""
    
    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
    ]

    def compose(self):
        yield Header()
        yield TextArea(id="memory-editor", show_line_numbers=True)
        yield Footer()

    def on_mount(self) -> None:
        editor = self.query_one("#memory-editor", TextArea)
        global_mem = load_memory("global")
        editor.load_text(global_mem if global_mem else "## Global Memory\n\nAdd facts about yourself here.")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        # Removed auto-save to reduce disk I/O on every keystroke
        pass

    def action_save(self) -> None:
        editor = self.query_one("#memory-editor", TextArea)
        save_memory("global", editor.text)
        self.notify("Memory saved!")

    def action_back(self) -> None:
        self.app.pop_screen()


class HistorySelectScreen(Screen):
    """Select a model to view its history."""
    
    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
    ]

    def compose(self):
        yield Header()
        yield ListView(id="history-model-list")
        yield Footer()

    def on_mount(self) -> None:
        import os
        list_view = self.query_one("#history-model-list", ListView)
        
        if not os.path.exists(HISTORY_DIR):
            return
            
        for d in sorted(os.listdir(HISTORY_DIR)):
            path = os.path.join(HISTORY_DIR, d)
            if os.path.isdir(path):
                list_view.append(ListItem(Label(d)))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if item:
            label = item.query_one(Label)
            model_name = str(getattr(label, "renderable", label.render()))
            self.app.push_screen(HistoryBrowseScreen(model_name))

    def action_back(self) -> None:
        self.app.pop_screen()


class HistoryBrowseScreen(Screen):
    """Browse sessions for a specific model."""
    
    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self, model_name: str, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name

    def compose(self):
        yield Header()
        yield ListView(id="sessions-list")
        yield Footer()

    def on_mount(self) -> None:
        list_view = self.query_one("#sessions-list", ListView)
        sessions = list_sessions(self.model_name)
        
        for s in sessions[:20]:
            label = f"{s['start_time'][:19]} ({s['message_count']} msgs)"
            list_view.append(ListItem(Label(label)))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        list_view = self.query_one("#sessions-list", ListView)
        idx = list_view.index
        if idx is not None:
            sessions = list_sessions(self.model_name)
            if 0 <= idx < len(sessions):
                filename = sessions[idx]["filename"]
                messages = load_chat_session(self.model_name, filename)
                if messages:
                    self.app.active_model = self.model_name
                    self.app.push_screen(ChatScreen(self.model_name, initial_messages=messages))

    def action_back(self) -> None:
        self.app.pop_screen()


class ChatScreen(Screen):
    """Full-screen chat interface."""
    
    BINDINGS = [
        Binding("escape", "back", "Back to Menu", show=True),
        Binding("ctrl+l", "clear", "Clear Chat", show=True),
    ]

    def __init__(self, model_name: str, initial_messages: Optional[list] = None, context_length: Optional[int] = None, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.context_length = context_length or config.default_context_length
        self.messages = []
        
        if initial_messages:
            self.messages = initial_messages
        else:
            system_prompt = build_system_prompt(model_name)
            if system_prompt:
                self.messages.append({"role": "system", "content": system_prompt})

    def compose(self) -> ComposeResult:
        from .hardware import estimate_kv_cache_gb
        kv_cache_gb = estimate_kv_cache_gb(self.context_length, self.model_name)
        
        yield Header()
        yield Static(
            f"Model: [bold white]{self.model_name}[/bold white] | "
            f"Context: [cyan]{self.context_length//1024}k[/cyan] [dim](+{kv_cache_gb}GB VRAM)[/dim]",
            classes="chat-info"
        )
        yield ScrollableContainer(id="chat-display")
        yield Horizontal(
            Input(placeholder=f"Message {self.model_name}...", id="chat-input"),
            Button("Send", id="send-btn", variant="primary"),
            id="input-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self._render_history()

    def _render_history(self) -> None:
        display = self.query_one("#chat-display", ScrollableContainer)
        display.query(Static).remove()
        
        for msg in self.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content or role == "system":
                continue
            
            if role == "user":
                widget = Static(f"[bold purple]You:[/bold purple] {content}", classes="user-msg")
            elif role == "assistant":
                widget = Static(f"[bold white]AI:[/bold white] {content}", classes="ai-msg")
            elif role == "tool":
                widget = Static(f"[dim]Tool: {content[:200]}...[/dim]", classes="tool-msg")
            else:
                continue
            
            display.mount(widget)
        display.scroll_end(animate=False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self._handle_input(event.value)
        event.input.value = ""

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            input_widget = self.query_one("#chat-input", Input)
            await self._handle_input(input_widget.value)
            input_widget.value = ""

    async def _handle_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        
        if text.startswith("/"):
            self._handle_slash_command(text)
            return
        
        self.messages.append({"role": "user", "content": text})
        self._add_message("user", text)
        
        if not is_ollama_running():
            self._add_message("assistant", "[red]Ollama is not running.[/red]")
            return
        
        self._stream_response()

    def _handle_slash_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=2)
        cmd = parts[0].lower()
        
        if cmd == "/clear":
            system = [m for m in self.messages if m.get("role") == "system"]
            self.messages = system
            display = self.query_one("#chat-display", ScrollableContainer)
            display.query(Static).remove()
            self._add_message("system", "Chat cleared.")
            
        elif cmd == "/memory":
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub == "save" and len(parts) == 3:
                kv = parts[2].split(maxsplit=1)
                if len(kv) == 2:
                    key, val = kv
                    update_memory_entry(self.model_name, key, val)
                    self._add_message("system", f"Saved to memory: {key} -> {val}")
            elif sub == "clear":
                clear_memory(self.model_name)
                self._add_message("system", "Memory cleared.")
            else:
                mem = load_memory(self.model_name)
                self._add_message("system", mem if mem else "No memory.")
                
        elif cmd == "/memoryadd":
            target = parts[1].lower() if len(parts) > 1 else "chat"
            if target not in ("global", "chat"):
                self._add_message("system", "Usage: /memoryadd [global|chat]")
            else:
                self._extract_memory_task(target)
                
        elif cmd == "/addmemory" or "add above conversation to your memory" in cmd.lower():
            self._extract_memory_task("chat")
            
        else:
            self._add_message("system", f"Unknown command: {cmd}")

    @work(thread=True, exclusive=True)
    def _extract_memory_task(self, target: str) -> None:
        """Extract important info from conversation and save to memory."""
        from .memory import extract_and_update_memory
        
        if not is_ollama_running():
            self.app.call_from_thread(self._add_message, "system", "Ollama not running - cannot extract memory.")
            return
        
        self.app.call_from_thread(self._add_message, "system", f"Extracting key information for {target} memory...")
        
        try:
            result = extract_and_update_memory(self.model_name, self.messages, target=target)
            if result.startswith("Error:"):
                self.app.call_from_thread(self._add_message, "system", f"[red]{result}[/red]")
            else:
                self.app.call_from_thread(self._add_message, "system", f"[white][bold green]Facts added to {target} memory:[/bold green][/white]\n{result}")
                self.app.call_from_thread(self.notify, f"Memory updated ({target})")
        except Exception as e:
            self.app.call_from_thread(self._add_message, "system", f"Error extracting memory: {e}")

    def _add_message(self, role: str, content: str) -> None:
        display = self.query_one("#chat-display", ScrollableContainer)
        
        if role == "user":
            widget = Static(f"[bold purple]You:[/bold purple] {content}", classes="user-msg")
        elif role == "assistant":
            widget = Static(f"[bold white]AI:[/bold white] {content}", classes="ai-msg")
        elif role == "tool":
            widget = Static(f"[dim]Tool: {content[:300]}...[/dim]", classes="tool-msg")
        else:
            widget = Static(f"[dim]{content}[/dim]", classes="system-msg")
        
        display.mount(widget)
        display.scroll_end(animate=True)

    @work(thread=True, exclusive=True)
    def _stream_response(self) -> None:
        """Stream response from Ollama with tool support. Runs in a background thread."""
        from .tools import run_tool, TOOLS_SCHEMA
        
        tools_available = config.tools_enabled
        max_rounds = 15
        
        self.app.call_from_thread(self._add_message, "system", "Connecting to Ollama...")
        
        for round_num in range(max_rounds):
            full_response = ""
            tool_calls = []
            
            # Safely create and mount the response widget from the thread
            def prepare_response_widget():
                display = self.query_one("#chat-display", ScrollableContainer)
                widget = Static("", classes="ai-msg")
                display.mount(widget)
                return widget
            
            response_widget = self.app.call_from_thread(prepare_response_widget)
            
            try:
                kwargs = {}
                if tools_available:
                    kwargs["tools"] = TOOLS_SCHEMA
                
                kwargs["options"] = {"num_ctx": self.context_length}
                
                try:
                    for chunk in chat_stream(self.model_name, self.messages, 0.7, **kwargs):
                        if "error" in chunk:
                            err_msg = str(chunk['error'])
                            if "does not support tools" in err_msg and kwargs.get("tools"):
                                kwargs.pop("tools", None)
                                for chunk in chat_stream(self.model_name, self.messages, 0.7, **kwargs):
                                    if "error" in chunk:
                                        self.app.call_from_thread(self._add_message, "assistant", f"Error: {chunk['error']}")
                                        return
                                    msg = chunk.get("message", {})
                                    piece = msg.get("content", "")
                                    if piece:
                                        full_response += piece
                                        self.app.call_from_thread(response_widget.update, f"[bold white]AI:[/bold white] {full_response}")
                                    for tc in msg.get("tool_calls", []):
                                        tool_calls.append(tc)
                                break
                            else:
                                self.app.call_from_thread(self._add_message, "assistant", f"Error: {err_msg}")
                                return
                        
                        msg = chunk.get("message", {})
                        piece = msg.get("content", "")
                        if piece:
                            full_response += piece
                            self.app.call_from_thread(response_widget.update, f"[bold white]AI:[/bold white] {full_response}")
                        
                        for tc in msg.get("tool_calls", []):
                            tool_calls.append(tc)

                except Exception as e:
                    error_str = str(e)
                    if "does not support tools" in error_str and kwargs.get("tools"):
                        kwargs.pop("tools", None)
                        for chunk in chat_stream(self.model_name, self.messages, 0.7, **kwargs):
                            if "error" in chunk:
                                self.app.call_from_thread(self._add_message, "assistant", f"Error: {chunk['error']}")
                                return
                            msg = chunk.get("message", {})
                            piece = msg.get("content", "")
                            if piece:
                                full_response += piece
                                self.app.call_from_thread(response_widget.update, f"[bold white]AI:[/bold white] {full_response}")
                            for tc in msg.get("tool_calls", []):
                                tool_calls.append(tc)
                    else:
                        raise
                        
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                self.app.call_from_thread(self._add_message, "assistant", error_msg)
                return
            
            if not tool_calls:
                self.messages.append({"role": "assistant", "content": full_response})
                return
            
            self.messages.append({
                "role": "assistant", 
                "content": full_response, 
                "tool_calls": tool_calls
            })
            
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        args = {}
                
                self.app.call_from_thread(self._add_message, "tool", f"Calling {name}...")
                
                result = run_tool(name, **args)
                self.app.call_from_thread(self._add_message, "tool", f"{name}: {result[:500]}")
                self.messages.append({"role": "tool", "content": result})
        
        self.app.call_from_thread(self._add_message, "assistant", "[yellow]Tool call limit reached.[/yellow]")

    def action_clear(self) -> None:
        system = [m for m in self.messages if m.get("role") == "system"]
        self.messages = system
        display = self.query_one("#chat-display", ScrollableContainer)
        display.query(Static).remove()
        self._add_message("system", "Chat cleared.")

    def action_back(self) -> None:
        user_msgs = [m for m in self.messages if m.get("role") == "user"]
        if user_msgs:
            save_session(self.model_name, self.messages, 0.7, datetime.now())
        self.app.pop_screen()


class AIHubApp(App):
    """Main AIHub 0.1.4 Application."""

    TITLE = "AIHub 0.1.4"
    CSS = """
    Screen { background: $surface; }

    /* Search bar */
    .search-bar { height: auto; padding: 1 1 0 1; }
    #search-input { width: 1fr; }

    /* Category filter bar */
    #cat-filter-bar { height: auto; padding: 0 1; }
    .cat-btn { margin-right: 1; min-width: 10; }

    /* Hardware info bar */
    .hw-info { height: auto; padding: 0 2; background: $panel; }

    /* Model list items */
    .model-item { padding: 1; border-bottom: solid $panel; }
    .model-item.installed { border-left: thick green; }
    .model-item.incompatible { opacity: 0.5; }
    .model-name { width: 45; }
    .status-badge { width: 22; }
    .model-meta { color: $text-muted; }
    .model-badges { color: $accent; }
    .model-usecase { color: $text-muted; }

    /* Detail panel */
    .detail-panel { padding: 2; }
    .title { text-style: bold; width: 100%; margin-bottom: 1; }
    .desc { width: 90%; color: $text-muted; margin-bottom: 1; }
    .badges { color: $accent; margin-bottom: 1; }
    .actions { width: 100%; margin-top: 2; }

    /* Chat */
    #chat-display { height: 1fr; border: solid $primary; margin: 1; padding: 1; }
    .user-msg { text-align: right; color: #7c3aed; padding: 0 1; }
    .ai-msg { padding: 0 1; }
    .tool-msg { color: #10b981; padding: 0 1; }
    .system-msg { color: #888888; padding: 0 1; }
    #input-container { dock: bottom; height: auto; margin: 1; }
    #chat-input { width: 90%; }

    /* Context config modal */
    .modal-container { background: $panel; border: thick $primary; padding: 2;
                       width: 50%; height: auto; align: center middle; }
    .modal-actions { margin-top: 1; height: auto; }
    .modal-actions Button { margin-right: 1; }
    .chat-info { background: $panel; padding: 1; border-bottom: solid $primary;
                 text-align: center; }
    /* Main Menu */
    .main-menu-container { align: center middle; align-horizontal: center; height: 1fr; }
    #main-title { text-align: center; margin-bottom: 1; }
    #main-desc { text-align: center; margin-bottom: 2; }
    .main-menu-container Button { width: 40; margin-bottom: 1; }
    """
    
    def on_mount(self) -> None:
        self.active_model = None
        self.push_screen(MainMenuScreen())

    def on_unmount(self) -> None:
        """Unload the last active model from memory when quitting."""
        if hasattr(self, "active_model") and self.active_model:
            unload_model(self.active_model)


def launch_tui():
    """Entry point for TUI mode."""
    app = AIHubApp()
    app.run()
