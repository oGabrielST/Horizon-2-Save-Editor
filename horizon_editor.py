"""Native desktop interface for Horizon 2 Save Editor."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from native_core import SaveSession, load_catalog, read_folder, read_profile, revisions, validate_manifests, write_zip

TITLE = "Horizon 2 Save Editor"
VERSION = "0.4.0"
ASSETS = ("catalog.js", "README.md", "RESEARCH.md")


class Editor:
    def __init__(self, root):
        self.root = root
        self.catalog = load_catalog(Path(__file__).resolve().parent)
        self.cars = {c["id"]: c for c in self.catalog["cars"]}
        self.session = None
        self.source_folder = None
        self.files, self.manifests, self.available_revisions = {}, {}, []
        self.busy = False
        self.checkpoint = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="save-files")
        root.title(TITLE)
        root.geometry("1080x820")
        root.minsize(900, 720)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f7")
        style.configure("TLabel", background="#f3f5f7", foreground="#263140", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        style.configure("Sub.TLabel", foreground="#596779")
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        style.configure("Primary.TButton", background="#d75c27", foreground="white")
        style.map("Primary.TButton", background=[("active", "#b54718")])
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TNotebook.Tab", padding=(18, 9), font=("Segoe UI", 10))
        outer = ttk.Frame(root, padding=22)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text=f"v{VERSION}  |  Native desktop editor  |  Local processing", style="Sub.TLabel").pack(anchor="w", pady=(2, 14))
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Open backup folder", command=self.open_folder, style="Primary.TButton").pack(side="left")
        ttk.Button(toolbar, text="Discard changes", command=self.discard).pack(side="left", padx=8)
        ttk.Button(toolbar, text="How to use", command=self.help).pack(side="left")
        ttk.Button(toolbar, text="Export edited copy (.zip)", command=self.export, style="Primary.TButton").pack(side="right")
        revision_bar = ttk.Frame(outer)
        revision_bar.pack(fill="x", pady=12)
        ttk.Label(revision_bar, text="Revision").pack(side="left", padx=(0, 8))
        self.revision = ttk.Combobox(revision_bar, state="readonly", width=22)
        self.revision.pack(side="left")
        self.revision.bind("<<ComboboxSelected>>", self.select_revision)
        self.folder_label = tk.StringVar(value="Select a complete, extracted player-1 backup folder.")
        ttk.Label(revision_bar, textvariable=self.folder_label, style="Sub.TLabel", wraplength=650).pack(side="left", padx=14)
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.profile_tab()
        self.garage_tab()
        self.progress_tab()
        self.story_tab()
        ttk.Label(outer, text="Prepared changes", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 4))
        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="x")
        self.log = tk.Text(log_frame, height=4, wrap="word", state="disabled", font=("Consolas", 10), relief="flat")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")
        self.status = tk.StringVar(value="Ready. Source backups are never overwritten.")
        ttk.Label(outer, textvariable=self.status, style="Sub.TLabel", wraplength=1000).pack(anchor="w", pady=(9, 0))
        # Reserve the toolbar/status area; let the notebook shrink on smaller screens.
        for widget in outer.winfo_children():
            widget.pack_forget()
        for row, widget in enumerate(outer.winfo_children()):
            widget.grid(row=row, column=0, sticky="nsew" if widget is self.tabs else "ew",
                        pady={1: (2, 14), 3: 10, 5: (8, 4), 7: (8, 0)}.get(row, 0))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        self.filter_cars()
        self.filter_events()
        for index in range(4):
            self.tabs.tab(index, state="disabled")

    def tab(self, title):
        frame = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(frame, text=title)
        return frame

    @staticmethod
    def tree(parent, columns, widths):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=6)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=5)
        for name, width in zip(columns, widths):
            tree.heading(name, text=name)
            tree.column(name, width=width, minwidth=55)
        scrollbar = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    def profile_tab(self):
        frame = self.tab("Profile")
        ttk.Label(frame, text="Edit XP and resources", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="XP does not rewrite the stored level. The game determines progression and rewards.", style="Sub.TLabel").pack(anchor="w", pady=(6, 18))
        form = ttk.Frame(frame)
        form.pack(anchor="w")
        self.fields = {}
        for row, (key, label) in enumerate((("Credits", "Credits"), ("XP", "XP"), ("Spins", "Wheelspins"), ("Tokens", "Available skill tokens"))):
            ttk.Label(form, text=label, width=25).grid(row=row, column=0, sticky="w", pady=9)
            variable = tk.StringVar()
            self.fields[key] = variable
            ttk.Entry(form, textvariable=variable, width=28, font=("Segoe UI", 12)).grid(row=row, column=1, sticky="w")
        ttk.Button(frame, text="Apply profile changes", command=lambda: self.run(self.apply_profile)).pack(anchor="w", pady=16)
        ttk.Label(frame, text="Profile fields are also applied when you export. Other action buttons prepare changes immediately.", style="Sub.TLabel", wraplength=850).pack(anchor="w")

    def garage_tab(self):
        frame = self.tab("Garage")
        panels = ttk.Panedwindow(frame, orient="horizontal")
        panels.pack(fill="both", expand=True)
        left, right = ttk.Frame(panels), ttk.Frame(panels)
        panels.add(left, weight=1)
        panels.add(right, weight=1)
        ttk.Label(left, text="Your garage", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.garage_tree = self.tree(left, ("ID", "Car", "Active"), (55, 280, 60))
        actions = ttk.Frame(left)
        actions.pack(fill="x")
        ttk.Button(actions, text="Set active", command=lambda: self.run(lambda: self.session.set_current_car(self.selected_garage()))).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Duplicate", command=lambda: self.run(lambda: self.session.duplicate_car(self.selected_garage()))).pack(side="left")
        ttk.Label(right, text="Stock model catalog", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=(12, 0))
        self.car_search = tk.StringVar()
        search = ttk.Entry(right, textvariable=self.car_search)
        search.pack(fill="x", padx=(12, 0), pady=6)
        self.car_search.trace_add("write", lambda *_: self.filter_cars())
        self.catalog_tree = self.tree(right, ("Model ID", "Model", "Price"), (70, 260, 85))
        actions = ttk.Frame(right)
        actions.pack(fill="x")
        ttk.Button(actions, text="Add stock car", command=lambda: self.run(lambda: self.session.add_stock(self.selected_model()))).pack(side="left", padx=(12, 6))
        ttk.Button(actions, text="Replace selected car", command=self.replace_car).pack(side="left")
        ttk.Label(frame, text="Search by model name or ID. Replacement resets stock settings and removes purchased parts. Content must be installed for cars that require it.", style="Sub.TLabel", wraplength=920).pack(anchor="w", pady=(12, 0))

    def progress_tab(self):
        frame = self.tab("Progress")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)
        left, right = ttk.Frame(frame), ttk.Frame(frame)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(left, text="Perks", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Button(left, text="Unlock all 25 perks", command=lambda: self.run(lambda: self.session.apply_preset("perks"))).pack(anchor="w", pady=5)
        ttk.Label(left, text="Experimental progression", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(10, 5))
        actions = ttk.Frame(left)
        actions.pack(fill="x")
        for index, (key, label) in enumerate((("destinations", "Unlock destinations"), ("events", "Unlock mainland events"), ("discover", "Discover map items"), ("boards", "Collect existing boards"), ("buckets", "Complete solo bucket lists"), ("championships", "Set championship history"))):
            ttk.Button(actions, text=label, command=lambda k=key: self.run(lambda: self.session.apply_preset(k))).grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 8), pady=4)
        ttk.Label(left, text="In-game testing pending. These records do not run story scripts or grant rewards. There is no verified complete-everything action.", style="Sub.TLabel", wraplength=410).pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="Find event", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.event_search = tk.StringVar()
        ttk.Entry(right, textvariable=self.event_search).pack(fill="x", pady=6)
        self.event_search.trace_add("write", lambda *_: self.filter_events())
        ttk.Button(right, text="Unlock selected event", command=lambda: self.run(lambda: self.session.unlock_event(self.selection(self.event_tree, "Select an event.")))).pack(side="bottom", anchor="w")
        self.event_tree = self.tree(right, ("Event ID", "Event", "Region"), (65, 210, 75))

    def story_tab(self):
        frame = self.tab("Advanced story")
        ttk.Label(frame, text="Experimental flags and counters", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Story dependencies are not fully mapped. Existing enum values remain read-only.", style="Sub.TLabel").pack(anchor="w", pady=(4, 12))
        self.story_object = ttk.Combobox(frame, state="readonly", values=("CareerState", "iestate"), width=30)
        self.story_object.set("CareerState")
        self.story_object.pack(anchor="w")
        self.story_object.bind("<<ComboboxSelected>>", lambda _: self.refresh_story())
        self.story_tree = self.tree(frame, ("Property", "Value"), (450, 350))
        self.story_tree.bind("<<TreeviewSelect>>", self.story_selected)
        bottom = ttk.Frame(frame)
        bottom.pack(fill="x")
        ttk.Label(bottom, text="New value").pack(side="left", padx=(0, 8))
        self.story_value = tk.StringVar()
        ttk.Entry(bottom, textvariable=self.story_value, width=40).pack(side="left")
        ttk.Button(bottom, text="Apply selected property", command=lambda: self.run(self.apply_story)).pack(side="left", padx=10)

    def filter_cars(self):
        query = self.car_search.get().strip().casefold()
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        for car in self.catalog["cars"]:
            if car["eligible"] and query in f"{car['id']} {car['name']}".casefold():
                self.catalog_tree.insert("", "end", iid=str(car["id"]), values=(car["id"], car["name"], f"{car['price']:,}"))

    def filter_events(self):
        query = self.event_search.get().strip().casefold()
        self.event_tree.delete(*self.event_tree.get_children())
        for event in self.catalog["progression"]["events"]:
            if query in f"{event['id']} {event['name']} {event['region']}".casefold():
                self.event_tree.insert("", "end", iid=str(event["id"]), values=(event["id"], event["name"], event["region"]))

    @staticmethod
    def selection(tree, error):
        selected = tree.selection()
        if not selected:
            raise ValueError(error)
        return int(selected[0])

    def selected_garage(self):
        return self.selection(self.garage_tree, "Select a car in your garage.")

    def selected_model(self):
        return self.selection(self.catalog_tree, "Select a stock model in the catalog.")

    def replace_car(self):
        def action():
            ident, model = self.selected_garage(), self.selected_model()
            if messagebox.askyesno("Replace car", f"Replace garage car #{ident} with {self.cars[model]['name']}?\n\nThis resets its stock settings and removes purchased parts in the exported copy.", parent=self.root):
                self.session.add_stock(model, ident)
        self.run(action)

    def apply_story(self):
        selected = self.story_tree.selection()
        if not selected:
            raise ValueError("Select a story property.")
        self.session.set_story(self.story_object.get(), selected[0], self.story_value.get().strip())
        self.refresh_story()

    def story_selected(self, _event=None):
        selected = self.story_tree.selection()
        if selected and self.session:
            self.story_value.set(self.session.xml.get(self.story_object.get(), selected[0]))

    def refresh_story(self):
        self.story_tree.delete(*self.story_tree.get_children())
        self.story_value.set("")
        if self.session:
            ident = self.story_object.get()
            obj = self.session.xml.objects.get(ident)
            if obj:
                for name in obj["props"]:
                    self.story_tree.insert("", "end", iid=name, values=(name, self.session.xml.get(ident, name)))

    def profile_values(self):
        return (str(read_profile(self.session.profile, "Credits")), str(read_profile(self.session.profile, "XP")),
                self.session.xml.get("TombolaState", "Spins"), self.session.xml.get("skills", "CurrentSkillTokensTotal"))

    def apply_profile(self):
        self.session.apply_profile(*(v.get().strip() for v in self.fields.values()))

    def fingerprint(self):
        return (tuple(self.session.log), tuple(v.get() for v in self.fields.values())) if self.session else None

    def confirm_discard(self):
        return self.fingerprint() == self.checkpoint or messagebox.askyesno("Unsaved changes", "Discard changes that have not been exported?", parent=self.root)

    def background(self, task, callback, status):
        self.busy = True
        self.status.set(status)
        self.root.configure(cursor="watch")
        future = self.pool.submit(task)
        def poll():
            if not future.done():
                self.root.after(60, poll)
                return
            self.busy = False
            self.root.configure(cursor="")
            try:
                callback(future.result())
            except Exception as error:
                self.error(error)
        self.root.after(60, poll)

    def open_folder(self):
        if self.busy or not self.confirm_discard():
            return
        folder = filedialog.askdirectory(title="Select the complete player-1 backup folder", parent=self.root)
        if not folder:
            return
        self.background(lambda: read_folder(folder), lambda files: self.load_files(files, Path(folder)), "Reading backup and validating manifest hashes...")

    def load_files(self, files, folder):
        manifests = validate_manifests(files)
        found = revisions(manifests)
        session = SaveSession(files, found[0], manifests, self.catalog)
        self.install_session(session)
        self.files, self.manifests, self.available_revisions = files, manifests, found
        self.source_folder = folder
        self.revision.configure(values=[r["id"] for r in found])
        self.revision.current(0)
        self.folder_label.set(str(folder))
        for index in range(4):
            self.tabs.tab(index, state="normal")
        self.tabs.select(0)
        self.status.set(f"Loaded revision {found[0]['id']}. {len(session.garage())} cars. Source backup preserved.")

    def install_session(self, session):
        # Resolve optional UI fields before replacing the previous valid session.
        try:
            values = (str(read_profile(session.profile, "Credits")), str(read_profile(session.profile, "XP")),
                      session.xml.get("TombolaState", "Spins"), session.xml.get("skills", "CurrentSkillTokensTotal"))
        except Exception:
            session.close()
            raise
        if self.session:
            self.session.close()
        self.session = session
        for variable, value in zip(self.fields.values(), values):
            variable.set(value)
        self.refresh()
        self.refresh_story()
        self.checkpoint = self.fingerprint()

    def select_revision(self, _event=None):
        if not self.session:
            return
        previous = next(i for i, r in enumerate(self.available_revisions) if r["id"] == self.session.revision["id"])
        index = self.revision.current()
        if self.busy or not self.confirm_discard():
            self.revision.current(previous)
            return
        try:
            self.install_session(SaveSession(self.files, self.available_revisions[index], self.manifests, self.catalog))
            self.status.set("Revision loaded. Changes are prepared in memory.")
        except Exception as error:
            self.revision.current(previous)
            self.error(error)

    def discard(self):
        if self.busy or not self.session or not self.confirm_discard():
            return
        self.run(lambda: self.install_session(SaveSession(self.files, self.session.revision, self.manifests, self.catalog)))

    def refresh(self):
        selected = self.garage_tree.selection()
        self.garage_tree.delete(*self.garage_tree.get_children())
        active = read_profile(self.session.profile, "CareerCar")
        for car in self.session.garage():
            model = self.cars.get(car["CarId"], {}).get("name", f"Model #{car['CarId']}")
            self.garage_tree.insert("", "end", iid=str(car["Id"]), values=(car["Id"], model, "Yes" if car["Id"] == active else ""))
        if selected and self.garage_tree.exists(selected[0]):
            self.garage_tree.selection_set(selected[0])
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(self.session.log) or "No changes prepared.")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run(self, action):
        if self.busy:
            return
        if not self.session:
            messagebox.showinfo(TITLE, "Open a backup folder first.", parent=self.root)
            return
        try:
            action()
            self.refresh()
            self.status.set("Changes prepared in memory. Export to create an edited copy.")
        except Exception as error:
            self.error(error)

    def error(self, error):
        self.status.set("Operation failed. The source backup has not been modified.")
        messagebox.showerror(TITLE, str(error), parent=self.root)

    def export(self):
        if self.busy or not self.session:
            return
        destination = filedialog.asksaveasfilename(title="Export edited save", defaultextension=".zip", initialfile="Horizon-2-edited-save.zip", filetypes=[("ZIP archive", "*.zip")], parent=self.root)
        if not destination:
            return
        try:
            self.apply_profile()
            files = self.session.export_files()
            self.refresh()
            exported = self.fingerprint()
        except Exception as error:
            self.error(error)
            return
        def finished(_result):
            self.checkpoint = exported
            self.status.set(f"Exported: {destination}")
            messagebox.showinfo("Export complete", "Edited copy exported successfully.\n\nClose the game and Azimuth before replacing the active save. Keep your original backup.\n\n" + destination, parent=self.root)
        self.background(lambda: write_zip(destination, files, self.source_folder), finished, "Writing and validating edited copy...")

    def help(self):
        messagebox.showinfo("How to use", "1. Open a complete, extracted player-1 backup folder.\n2. Choose Profile, Garage, Progress or Advanced story.\n3. Prepare changes and export an edited ZIP copy.\n4. Close the game and Azimuth. Back up the active save.\n5. Extract the ZIP and replace the active player-1 folder.\n\nActive location: data/titles/1A96545B/saves/player-1\n\nXP, car editing and perks were reported working in the earlier editor. The native version uses a new Python backend; in-game testing of this version is still required. Other progression options remain experimental.\n\nNo browser, local server, account or internet connection is required. The source backup is never overwritten.", parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo(TITLE, "Wait for the current file operation to finish.", parent=self.root)
            return
        if not self.confirm_discard():
            return
        if self.session:
            self.session.close()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def smoke_test(output, fixture=None):
    """Construct native widgets and optionally exercise a real fixture without displaying windows."""
    result = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False))}
    root = app = None
    try:
        root = tk.Tk()
        root.withdraw()
        app = Editor(root)
        root.update_idletasks()
        assert root.title() == TITLE and len(app.tabs.tabs()) == 4
        assert set(app.fields) == {"Credits", "XP", "Spins", "Tokens"}
        assert len(app.catalog_tree.get_children()) == 334
        if fixture:
            files = read_folder(fixture)
            app.load_files(files, fixture)
            before = read_profile(app.session.profile, "Level")
            app.fields["XP"].set("456789")
            app.run(app.apply_profile)
            app.session.add_stock(247)
            app.session.apply_preset("perks")
            app.refresh()
            exported = app.session.export_files()
            assert read_profile(app.session.profile, "XP") == 456789
            assert read_profile(app.session.profile, "Level") == before
            assert len(app.garage_tree.get_children()) == len(app.session.garage())
            assert app.fields["XP"].get() == "456789"
            validate_manifests(exported)
            result["fixture_checked"] = True
        result.update(ok=True, native_editor=True, tabs=4, browser_required=False)
    except Exception as error:
        result.update(ok=False, error=str(error))
    finally:
        if app:
            if app.session:
                app.session.close()
            app.pool.shutdown(wait=False, cancel_futures=True)
        if root:
            root.destroy()
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON")
    parser.add_argument("--fixture", type=Path, help="Optional save fixture for the self-test")
    args = parser.parse_args()
    if args.self_test:
        return smoke_test(args.self_test, args.fixture)
    root = tk.Tk()
    root.withdraw()
    try:
        Editor(root)
        root.deiconify()
        root.mainloop()
    except Exception as error:
        messagebox.showerror(TITLE, f"Could not start the editor.\n\n{error}", parent=root)
        root.destroy()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
