"""MiniScreeps v8 — Тултипы на карте и исправленная справка.
Запуск: python mini_screeps.py
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
from collections import deque
from types import SimpleNamespace
import random
import os
import time
import traceback
import re
import sys

# ---------------- Настройки ----------------
TILE = 26
W, H = 26, 16

WORKER_COST, SOLDIER_COST, TURRET_COST = 50, 100, 150
WORKER_HP, SOLDIER_HP, TURRET_HP = 100, 150, 200
WORKER_ATK, SOLDIER_ATK, TURRET_ATK = 10, 50, 30
TURRET_RANGE = 3
WORKER_MINE, WORKER_CAP = 5, 20
CORE_HP, CORE_START_ENERGY = 1000, 150
RESOURCE_AMOUNT, RESOURCE_SPOTS = 1500, 8

BOT_FILE = "bot.py"

# ---------------- Безопасное окружение ----------------
def get_safe_builtins(log_func):
    def custom_print(*args, **kwargs):
        msg = " ".join(str(a) for a in args)
        log_func(f"[BOT] {msg}")
    return {
        "len": len, "min": min, "max": max, "abs": abs, "sum": sum,
        "sorted": sorted, "range": range, "enumerate": enumerate,
        "zip": zip, "list": list, "dict": dict, "set": set,
        "tuple": tuple, "int": int, "float": float, "str": str,
        "bool": bool, "any": any, "all": all, "round": round,
        "print": custom_print, "next": next, "iter": iter,
        "map": map, "filter": filter, "isinstance": isinstance,
    }

# ---------------- Движок ----------------
class Unit:
    __slots__ = ("id", "owner", "kind", "x", "y", "hp", "carry", "cooldown")
    def __init__(self, uid, owner, kind, x, y, hp):
        self.id = uid; self.owner = owner; self.kind = kind
        self.x, self.y, self.hp = x, y, hp
        self.carry = 0; self.cooldown = 0

class Core:
    __slots__ = ("owner", "x", "y", "hp", "energy")
    def __init__(self, owner, x, y):
        self.owner, self.x, self.y = owner, x, y
        self.hp = CORE_HP; self.energy = CORE_START_ENERGY

class Resource:
    __slots__ = ("x", "y", "amount")
    def __init__(self, x, y, amount):
        self.x, self.y, self.amount = x, y, amount

class World:
    def __init__(self, seed=42):
        self.units = {}
        self.next_uid = 1
        self.resources = {}
        self.walls = set()
        self.tick = 0
        self.player_core = Core("player", 2, H // 2)
        self.enemy_core  = Core("enemy",  W - 3, H // 2)
        rng = random.Random(seed)
        
        for _ in range(20):
            x, y = rng.randint(5, W-6), rng.randint(2, H-3)
            if abs(x - 2) < 4 or abs(x - (W-3)) < 4: continue
            self.walls.add((x, y))
            if rng.random() > 0.5: self.walls.add((x+1, y))

        for _ in range(RESOURCE_SPOTS):
            while True:
                x, y = rng.randint(4, W - 5), rng.randint(1, H - 2)
                if (x, y) in self.resources or (x, y) in self.walls: continue
                if (x, y) in [(2, H//2), (W-3, H//2)]: continue
                self.resources[(x, y)] = Resource(x, y, RESOURCE_AMOUNT)
                break
                
        for _ in range(2):
            self.spawn("player", "worker")
            self.spawn("enemy",  "worker")
            
        self.build_turret("player", 4, H//2 - 2)
        self.build_turret("enemy", W-5, H//2 + 2)

    def core_of(self, owner):
        return self.player_core if owner == "player" else self.enemy_core

    def is_blocked(self, x, y, mover):
        if not (0 <= x < W and 0 <= y < H): return True
        if (x, y) in self.walls: return True
        if (x, y) == (self.player_core.x, self.player_core.y): return True
        if (x, y) == (self.enemy_core.x,  self.enemy_core.y):  return True
        for u in self.units.values():
            if u.x == x and u.y == y:
                if u.kind == "turret": return True
                if u.owner != mover: return True
        return False

    def free_spot_near(self, cx, cy, radius=3):
        spots = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx == 0 and dy == 0: continue
                nx, ny = cx + dx, cy + dy
                if self.is_blocked(nx, ny, "neutral"): continue
                if any(u.x == nx and u.y == ny for u in self.units.values()): continue
                spots.append((nx, ny))
        if not spots: return None
        spots.sort(key=lambda p: abs(p[0]-cx) + abs(p[1]-cy))
        return spots[0]

    def spawn(self, owner, kind):
        core = self.core_of(owner)
        spot = self.free_spot_near(core.x, core.y, 3)
        if spot is None: return None
        x, y = spot
        hp = WORKER_HP if kind == "worker" else SOLDIER_HP
        uid = self.next_uid; self.next_uid += 1
        self.units[uid] = Unit(uid, owner, kind, x, y, hp)
        return uid

    def build_turret(self, owner, x, y):
        if not (0 <= x < W and 0 <= y < H): return False
        if (x, y) in self.walls: return False
        if any(u.x == x and u.y == y for u in self.units.values()): return False
        
        uid = self.next_uid; self.next_uid += 1
        u = Unit(uid, owner, "turret", x, y, TURRET_HP)
        self.units[uid] = u
        return True

    def next_step(self, x, y, tx, ty, owner):
        if (x, y) == (tx, ty): return None
        if self.is_blocked(tx, ty, owner) and abs(x-tx) + abs(y-ty) <= 1: return None
        targets = {(tx, ty)}
        if self.is_blocked(tx, ty, owner):
            targets = set()
            for dx, dy in ((0,1),(0,-1),(1,0),(-1,0)):
                nx, ny = tx + dx, ty + dy
                if not self.is_blocked(nx, ny, owner): targets.add((nx, ny))
        q = deque([(x, y)])
        seen = {(x, y): None}
        found = None
        while q:
            cx, cy = q.popleft()
            if (cx, cy) in targets and (cx, cy) != (x, y):
                found = (cx, cy); break
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in seen or self.is_blocked(nx, ny, owner): continue
                seen[(nx, ny)] = (cx, cy)
                q.append((nx, ny))
        if found is None: return None
        cur = found
        while seen[cur] != (x, y):
            cur = seen[cur]
        return (cur[0] - x, cur[1] - y)

    def apply(self, owner, a):
        t = a.get("action")
        if t == "spawn":
            kind = a.get("kind")
            cost = WORKER_COST if kind == "worker" else SOLDIER_COST
            core = self.core_of(owner)
            if kind in ("worker", "soldier") and core.energy >= cost:
                if self.spawn(owner, kind) is not None: core.energy -= cost
        elif t == "build_turret":
            core = self.core_of(owner)
            if core.energy >= TURRET_COST:
                if self.build_turret(owner, int(a["x"]), int(a["y"])):
                    core.energy -= TURRET_COST
        elif t == "move_to":
            u = self.units.get(a.get("unit_id"))
            if not u or u.owner != owner or u.kind == "turret": return
            step = self.next_step(u.x, u.y, int(a["x"]), int(a["y"]), owner)
            if step:
                nx, ny = u.x + step[0], u.y + step[1]
                if not self.is_blocked(nx, ny, owner): u.x, u.y = nx, ny
        elif t == "mine":
            u = self.units.get(a.get("unit_id"))
            if not u or u.owner != owner or u.kind != "worker": return
            r = self.resources.get((u.x, u.y))
            if r and r.amount > 0 and u.carry < WORKER_CAP:
                take = min(WORKER_MINE, WORKER_CAP - u.carry, r.amount)
                u.carry += take; r.amount -= take
        elif t == "deposit":
            u = self.units.get(a.get("unit_id"))
            if not u or u.owner != owner or u.kind != "worker": return
            core = self.core_of(owner)
            if abs(u.x - core.x) + abs(u.y - core.y) <= 1:
                core.energy += u.carry; u.carry = 0
        elif t == "attack":
            u = self.units.get(a.get("unit_id"))
            if not u or u.owner != owner or u.cooldown > 0: return
            dmg = SOLDIER_ATK if u.kind == "soldier" else WORKER_ATK
            tgt = self.units.get(a.get("target_id", -1))
            if tgt and tgt.owner != owner and abs(u.x-tgt.x) + abs(u.y-tgt.y) <= 1:
                tgt.hp -= dmg; u.cooldown = 1; return
            oc = self.core_of("enemy" if owner == "player" else "player")
            if abs(u.x-oc.x) + abs(u.y-oc.y) <= 1:
                oc.hp -= dmg; u.cooldown = 1

    def step(self, player_actions, enemy_actions):
        self.tick += 1
        acted = set()
        for a in player_actions + enemy_actions:
            uid = a.get("unit_id")
            if uid is not None:
                if uid in acted: continue
                acted.add(uid)
            owner = "player" if a in player_actions else "enemy"
            self.apply(owner, a)
            
        for u in self.units.values():
            if u.kind == "turret" and u.cooldown == 0:
                targets = [e for e in self.units.values() if e.owner != u.owner and abs(e.x-u.x)+abs(e.y-u.y) <= TURRET_RANGE]
                if targets:
                    targets.sort(key=lambda e: abs(e.x-u.x) + abs(e.y-u.y))
                    targets[0].hp -= TURRET_ATK
                    u.cooldown = 1

        for u in list(self.units.values()):
            if u.cooldown > 0: u.cooldown -= 1
            if u.hp <= 0: del self.units[u.id]

# ---------------- API ----------------
class USnap:
    def __init__(self, u):
        self.id, self.kind = u.id, u.kind
        self.x, self.y, self.hp = u.x, u.y, u.hp
        self.carry = u.carry

class State:
    def __init__(self, world, owner, memory):
        self.tick = world.tick
        self.W, self.H = W, H
        self.memory = memory
        core = world.core_of(owner)
        ecore = world.core_of("enemy" if owner == "player" else "player")
        self.core = SimpleNamespace(x=core.x, y=core.y, hp=core.hp, energy=core.energy)
        self.enemy_core = SimpleNamespace(x=ecore.x, y=ecore.y, hp=ecore.hp)
        self.units = [USnap(u) for u in world.units.values() if u.owner == owner]
        self.enemies = [USnap(u) for u in world.units.values() if u.owner != owner]
        self.resources = [SimpleNamespace(x=r.x, y=r.y, amount=r.amount) for r in world.resources.values() if r.amount > 0]
        self.walls = world.walls

class API:
    def __init__(self): self.actions = []
    def spawn(self, kind): self.actions.append({"action": "spawn", "kind": kind})
    def build_turret(self, x, y): self.actions.append({"action": "build_turret", "x": int(x), "y": int(y)})
    def move_to(self, uid, x, y): self.actions.append({"action": "move_to", "unit_id": uid, "x": int(x), "y": int(y)})
    def mine(self, uid): self.actions.append({"action": "mine", "unit_id": uid})
    def deposit(self, uid): self.actions.append({"action": "deposit", "unit_id": uid})
    def attack(self, uid, target_id): self.actions.append({"action": "attack", "unit_id": uid, "target_id": target_id})

# ---------------- Код бота ----------------
STARTER_CODE = '''# Добро пожаловать в MiniScreeps v8!
# Наведите мышку на любого юнита на карте, чтобы увидеть его ID и здоровье.

def tick(state, api):
    core = state.core
    workers = [u for u in state.units if u.kind == "worker"]
    soldiers = [u for u in state.units if u.kind == "soldier"]
    turrets = [u for u in state.units if u.kind == "turret"]

    if core.energy >= 150 and len(turrets) < 2:
        api.build_turret(core.x + 2, core.y + 2)
        
    if len(workers) < 6 and core.energy >= 50:
        api.spawn("worker")
    elif core.energy >= 100 and len(soldiers) < 8:
        api.spawn("soldier")

    if state.resources:
        for w in workers:
            if w.id not in state.memory:
                idx = len(state.memory) % len(state.resources)
                r = state.resources[idx]
                state.memory[w.id] = (r.x, r.y)

            target_x, target_y = state.memory[w.id]

            if w.carry >= 20:
                if abs(w.x - core.x) + abs(w.y - core.y) <= 1:
                    api.deposit(w.id)
                else:
                    api.move_to(w.id, core.x, core.y)
            else:
                if (w.x, w.y) == (target_x, target_y):
                    api.mine(w.id)
                else:
                    api.move_to(w.id, target_x, target_y)

    for s in soldiers:
        target_enemy = None
        for e in state.enemies:
            if abs(e.x - s.x) + abs(e.y - s.y) <= 1:
                target_enemy = e
                break
                
        if target_enemy:
            api.attack(s.id, target_enemy.id)
        elif abs(s.x - state.enemy_core.x) + abs(s.y - state.enemy_core.y) <= 1:
            api.attack(s.id, -1)
        else:
            api.move_to(s.id, state.enemy_core.x, state.enemy_core.y)
'''

# ---------------- Внутренний ИИ ----------------
def enemy_bot(world):
    acts = []
    core = world.enemy_core
    workers = [u for u in world.units.values() if u.owner == "enemy" and u.kind == "worker"]
    soldiers = [u for u in world.units.values() if u.owner == "enemy" and u.kind == "soldier"]
    turrets = [u for u in world.units.values() if u.owner == "enemy" and u.kind == "turret"]

    if core.energy >= TURRET_COST and len(turrets) < 3:
        spots = [(core.x - 2, core.y - 2), (core.x - 2, core.y + 2), (core.x - 3, core.y)]
        for sx, sy in spots:
            if not world.is_blocked(sx, sy, "enemy"):
                acts.append({"action": "build_turret", "x": sx, "y": sy})
                break

    if len(workers) < 6 and core.energy >= WORKER_COST:
        acts.append({"action": "spawn", "kind": "worker"})
    elif core.energy >= SOLDIER_COST and len(soldiers) < 8:
        acts.append({"action": "spawn", "kind": "soldier"})

    for w in workers:
        if w.carry > 0:
            if abs(w.x - core.x) + abs(w.y - core.y) <= 1:
                acts.append({"action": "deposit", "unit_id": w.id})
            else:
                step = world.next_step(w.x, w.y, core.x, core.y, "enemy")
                if step: acts.append({"action": "move_to", "unit_id": w.id, "x": w.x+step[0], "y": w.y+step[1]})
        else:
            res = [r for r in world.resources.values() if r.amount > 0]
            if not res: continue
            r = min(res, key=lambda r: abs(r.x-w.x) + abs(r.y-w.y))
            if (w.x, w.y) == (r.x, r.y):
                acts.append({"action": "mine", "unit_id": w.id})
            else:
                step = world.next_step(w.x, w.y, r.x, r.y, "enemy")
                if step: acts.append({"action": "move_to", "unit_id": w.id, "x": w.x+step[0], "y": w.y+step[1]})

    for s in soldiers:
        tgt = None
        for u in world.units.values():
            if u.owner == "player" and abs(u.x-s.x) + abs(u.y-s.y) <= 1:
                tgt = u; break
        if tgt:
            acts.append({"action": "attack", "unit_id": s.id, "target_id": tgt.id})
        elif abs(s.x - world.player_core.x) + abs(s.y - world.player_core.y) <= 1:
            acts.append({"action": "attack", "unit_id": s.id, "target_id": -1})
        else:
            step = world.next_step(s.x, s.y, world.player_core.x, world.player_core.y, "enemy")
            if step: acts.append({"action": "move_to", "unit_id": s.id, "x": s.x+step[0], "y": s.y+step[1]})
    return acts

# ---------------- Редактор ----------------
class CodeEditor(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.text = tk.Text(self, font=("Consolas", 11), bg="#1e1e1e", fg="#d4d4d4", 
                            insertbackground="white", relief="flat", undo=True, wrap="none")
        self.scroll_y = tk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scroll_y.set)
        self.line_numbers = tk.Text(self, width=3, font=("Consolas", 11), bg="#252526", 
                                    fg="#858585", relief="flat", state="disabled")
        
        self.line_numbers.pack(side="left", fill="y")
        self.scroll_y.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        self.text.tag_configure("keyword", foreground="#569cd6")
        self.text.tag_configure("string", foreground="#ce9178")
        self.text.tag_configure("comment", foreground="#6a9955")
        self.text.tag_configure("api", foreground="#dcdcaa")
        self.text.tag_configure("number", foreground="#b5cea8")
        
        self.text.bind("<KeyRelease>", self.on_key_release)
        self.text.bind("<MouseWheel>", self.on_scroll)
        self.text.bind("<Button-4>", self.on_scroll)
        self.text.bind("<Button-5>", self.on_scroll)

    def on_scroll(self, event):
        self.line_numbers.yview_moveto(self.text.yview()[0])
        self.update_line_numbers()

    def on_key_release(self, event=None):
        self.highlight_syntax()
        self.update_line_numbers()

    def update_line_numbers(self):
        if self.text.index("end-1c") == "1.0": return
        last_line = int(self.text.index("end-1c").split(".")[0])
        current_lines = int(self.line_numbers.index("end-1c").split(".")[0])
        if last_line != current_lines:
            self.line_numbers.configure(state="normal")
            self.line_numbers.delete("1.0", "end")
            self.line_numbers.insert("1.0", "\n".join(str(i) for i in range(1, last_line + 1)))
            self.line_numbers.configure(state="disabled")
        self.line_numbers.yview_moveto(self.text.yview()[0])

    def highlight_syntax(self):
        self.text.tag_remove("keyword", "1.0", "end")
        self.text.tag_remove("string", "1.0", "end")
        self.text.tag_remove("comment", "1.0", "end")
        self.text.tag_remove("api", "1.0", "end")
        self.text.tag_remove("number", "1.0", "end")
        
        content = self.text.get("1.0", "end-1c")
        for m in re.finditer(r'\b(def|return|if|else|elif|for|in|while|True|False|None|and|or|not|import|from|as|pass|break|continue)\b', content):
            self.text.tag_add("keyword", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'("[^"\\]*(?:\\.[^"\\]*)*")|(\'[^\'\\]*(?:\\.[^\'\\]*)*\')', content):
            self.text.tag_add("string", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'#[^\n]*', content):
            self.text.tag_add("comment", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'\b(api|state)\.[a-zA-Z_]+\b', content):
            self.text.tag_add("api", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'\b\d+\b', content):
            self.text.tag_add("number", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")

    def get_code(self): return self.text.get("1.0", "end-1c")
    def set_code(self, code):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", code)
        self.highlight_syntax()
        self.update_line_numbers()

# ---------------- Интерфейс ----------------
class Game:
    def __init__(self, root):
        self.root = root
        self.world = None
        self.player_memory = {}
        self.running = False
        self.compiled_bot = None
        self.after_id = None
        self.last_mtime = 0
        self.delay_ms = 150
        self.current_tooltip = None
        
        self.setup_styles()
        self.build_ui()
        self.create_default_bot()
        self.reset()
        self.check_file_changes()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#2d2d2d')
        style.configure('TLabel', background='#2d2d2d', foreground='#ccc', font=("Helvetica", 10))
        style.configure('Header.TLabel', font=("Helvetica", 11, "bold"), foreground='#fff')
        style.configure('TButton', font=("Helvetica", 10, "bold"), padding=5)
        style.configure('Action.TButton', foreground='white', background='#0e639c')
        style.configure('Danger.TButton', foreground='white', background='#a33')
        style.map('Action.TButton', background=[('active', '#1177bb')])
        style.map('Danger.TButton', background=[('active', '#c44')])

    def build_ui(self):
        self.root.title("MiniScreeps v8 — Programmable RTS")
        self.root.geometry("1280x760")
        self.root.configure(bg="#1e1e1e")

        paned = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6, bg="#333")
        paned.pack(fill="both", expand=True)

        left_frame = ttk.Frame(paned)
        paned.add(left_frame, minsize=700)

        status_frame = ttk.Frame(left_frame)
        status_frame.pack(fill="x", pady=5)
        self.status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.status_var, style='Header.TLabel').pack(side="left", padx=10)

        canvas_frame = ttk.Frame(left_frame)
        canvas_frame.pack(fill="both", expand=True, padx=10)
        self.canvas = tk.Canvas(canvas_frame, width=W*TILE, height=H*TILE, bg="#141414", highlightthickness=0)
        self.canvas.pack()
        
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", lambda e: self.clear_tooltip())

        legend_frame = ttk.Frame(left_frame)
        legend_frame.pack(fill="x", pady=10, padx=10)
        ttk.Label(legend_frame, text="Легенда:", style='Header.TLabel').pack(side="left", padx=5)
        self.add_legend_item(legend_frame, "circle", "#5af", "Рабочий")
        self.add_legend_item(legend_frame, "square", "#5af", "Солдат")
        self.add_legend_item(legend_frame, "triangle", "#5af", "Турель")
        self.add_legend_item(legend_frame, "square", "#39f", "Ядро")
        self.add_legend_item(legend_frame, "circle", "#0c8", "Ресурсы")
        self.add_legend_item(legend_frame, "square", "#444", "Стены")

        right_frame = ttk.Frame(paned)
        paned.add(right_frame, minsize=450)

        header_frame = ttk.Frame(right_frame)
        header_frame.pack(fill="x", pady=5)
        ttk.Label(header_frame, text="Код бота (bot.py)", style='Header.TLabel').pack(side="left")
        ttk.Button(header_frame, text="📖 API Справочник", command=self.show_help).pack(side="right")
        
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill="x", pady=5)
        ttk.Button(btn_frame, text="▶ Запуск", command=self.reload_bot, style='Action.TButton').pack(side="left", padx=2)
        ttk.Button(btn_frame, text="⏸ Пауза", command=self.pause).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="⏭ Шаг", command=self.step_once).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="⟲ Сброс", command=self.reset, style='Danger.TButton').pack(side="right", padx=2)

        speed_frame = ttk.Frame(right_frame)
        speed_frame.pack(fill="x", pady=5)
        ttk.Label(speed_frame, text="Скорость:").pack(side="left")
        self.speed_combo = ttk.Combobox(speed_frame, values=["1x", "2x", "4x", "8x", "MAX"], state="readonly", width=5)
        self.speed_combo.set("1x")
        self.speed_combo.pack(side="left", padx=5)
        self.speed_combo.bind("<<ComboboxSelected>>", self.change_speed)

        self.editor = CodeEditor(right_frame)
        self.editor.pack(fill="both", expand=True, pady=5)

        self.logbox = tk.Text(right_frame, height=6, font=("Consolas", 9), bg="#1e1e1e", fg="#aaa", relief="flat")
        self.logbox.pack(fill="x", pady=(5, 0))
        self.logbox.configure(state="disabled")
        
        self.root.bind("<space>", lambda e: self.reload_bot() if not self.running else self.pause())

    # === ТУЛТИПЫ ===
    def clear_tooltip(self):
        self.canvas.delete("tooltip")
        self.current_tooltip = None

    def on_mouse_move(self, event):
        if not self.world: return
        gx = event.x // TILE
        gy = event.y // TILE
        
        if not (0 <= gx < W and 0 <= gy < H): return
        
        # Если тултип уже нарисован на этой клетке, не перерисовываем
        if self.current_tooltip == (gx, gy): return
        self.clear_tooltip()
        
        info = None
        w = self.world

        # Ищем юнитов
        for u in w.units.values():
            if u.x == gx and u.y == gy:
                owner_str = "Игрок" if u.owner == "player" else "Враг"
                if u.kind == "worker":
                    info = f"Рабочий ({owner_str})\nID: {u.id}\nHP: {u.hp}/{WORKER_HP}\nГруз: {u.carry}/{WORKER_CAP}"
                elif u.kind == "soldier":
                    info = f"Солдат ({owner_str})\nID: {u.id}\nHP: {u.hp}/{SOLDIER_HP}"
                elif u.kind == "turret":
                    info = f"Турель ({owner_str})\nID: {u.id}\nHP: {u.hp}/{TURRET_HP}"
                break
        
        # Ядра
        if not info:
            if (gx, gy) == (w.player_core.x, w.player_core.y):
                info = f"Ваше ядро\nHP: {w.player_core.hp}/{CORE_HP}\nЭнергия: {w.player_core.energy}"
            elif (gx, gy) == (w.enemy_core.x, w.enemy_core.y):
                info = f"Вражеское ядро\nHP: {w.enemy_core.hp}/{CORE_HP}"
        
        # Ресурсы
        if not info and (gx, gy) in w.resources:
            r = w.resources[(gx, gy)]
            if r.amount > 0:
                info = f"Ресурсы\nОстаток: {r.amount}"
                
        # Стены
        if not info and (gx, gy) in w.walls:
            info = "Препятствие (Стена)"

        if info:
            self.current_tooltip = (gx, gy)
            # Позиция тултипа (справа-снизу от объекта, с проверкой выхода за экран)
            tx = gx * TILE + TILE + 5
            ty = gy * TILE + 5
            if tx + 140 > W * TILE: tx = gx * TILE - 145
            if ty + 70 > H * TILE: ty = gy * TILE - 75

            self.canvas.create_rectangle(tx, ty, tx + 135, ty + 70, fill="#2d2d2d", outline="#555", tags="tooltip")
            self.canvas.create_text(tx + 8, ty + 8, text=info, anchor="nw", fill="#fff", font=("Consolas", 9), tags="tooltip")

    def show_help(self):
        help_win = tk.Toplevel(self.root)
        help_win.title("API Справочник")
        help_win.geometry("650x750")
        help_win.configure(bg="#1e1e1e")
        
        txt = tk.Text(help_win, font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4", wrap="word", padx=15, pady=15)
        txt.pack(fill="both", expand=True)
        
        # Настройка тегов
        txt.tag_configure("header", foreground="#569cd6", font=("Helvetica", 12, "bold"), spacing1=15, spacing3=8)
        txt.tag_configure("subheader", foreground="#4ec9b0", font=("Helvetica", 10, "bold"), spacing1=10, spacing3=5)
        txt.tag_configure("api", foreground="#dcdcaa")
        txt.tag_configure("number", foreground="#b5cea8")
        txt.tag_configure("string", foreground="#ce9178")

        help_text = """=== СПРАВКА ПО API ===
У вас есть функция tick(state, api). Она вызывается каждый игровой тик.

--- ОБЪЕКТ STATE (Состояние) ---
state.tick (int) - текущий тик.
state.memory (dict) - словарь для хранения памяти между тиками.
state.core - ваше ядро. Поля: x, y, hp, energy.
state.enemy_core - вражеское ядро. Поля: x, y, hp.
state.resources (list) - список ресурсов. Поля: x, y, amount.
state.walls (set) - кортежи (x, y) где находятся стены.
state.units (list) - ВАШИ юниты. Поля: id, kind, x, y, hp, carry.
state.enemies (list) - ВРАЖЕСКИЕ юниты. Поля: id, kind, x, y, hp.

--- ОБЪЕКТ API (Действия) ---
api.spawn(kind)
  Спавнит юнита. kind: "worker" или "soldier".
  Стоимость: Рабочий - 50, Солдат - 100.

api.build_turret(x, y)
  Строит защитную турель в координатах (x, y).
  Турель стреляет по врагам на расстоянии до 3 клеток.
  Стоимость: 150 энергии.

api.move_to(unit_id, x, y)
  Двигает юнита к координатам. Обходит стены.

api.mine(unit_id)
  Рабочий добывает ресурс. Должен стоять НА клетке с ресурсом.

api.deposit(unit_id)
  Рабочий сдает ресурсы. Должен стоять РЯДОМ с ядром.

api.attack(unit_id, target_id)
  Атаковать врага. Если target_id = -1, атакует ядро.

--- ХАРАКТЕРИСТИКИ ---
Рабочий: HP 100, Урон 10, Вместимость 20.
Солдат: HP 150, Урон 50.
Турель: HP 200, Урон 30, Радиус 3. Не двигается.

--- ПРИМЕЧАНИЯ ---
- В коде доступны: len, min, max, abs, range, sorted, next и др.
- Для вывода отладки используйте print().
- Код сохраняется в bot.py. Можно редактировать в VS Code.
"""
        txt.insert("1.0", help_text)
        
        # Применяем подсветку
        content = txt.get("1.0", "end-1c")
        for m in re.finditer(r'===.*===', content):
            txt.tag_add("header", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'---.*---', content):
            txt.tag_add("subheader", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'\b(api|state)\.\w+\b', content):
            txt.tag_add("api", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'\b\d+\b', content):
            txt.tag_add("number", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
        for m in re.finditer(r'"[^"]*"', content):
            txt.tag_add("string", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")
            
        txt.configure(state="disabled")

    def add_legend_item(self, parent, shape, color, text):
        f = ttk.Frame(parent)
        f.pack(side="left", padx=10)
        c = tk.Canvas(f, width=16, height=16, bg="#2d2d2d", highlightthickness=0)
        c.pack(side="left")
        if shape == "circle": c.create_oval(2, 2, 14, 14, fill=color, outline="white")
        elif shape == "square": c.create_rectangle(2, 2, 14, 14, fill=color, outline="white")
        elif shape == "triangle": c.create_polygon(8, 2, 14, 14, 2, 14, fill=color, outline="white")
        ttk.Label(f, text=text).pack(side="left", padx=3)

    def change_speed(self, event):
        val = self.speed_combo.get()
        self.delay_ms = {"1x": 150, "2x": 80, "4x": 40, "8x": 15, "MAX": 1}.get(val, 150)

    def log(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def create_default_bot(self):
        if not os.path.exists(BOT_FILE):
            with open(BOT_FILE, "w", encoding="utf-8") as f:
                f.write(STARTER_CODE)

    def check_file_changes(self):
        try:
            if os.path.exists(BOT_FILE):
                mtime = os.path.getmtime(BOT_FILE)
                if mtime > self.last_mtime:
                    self.last_mtime = mtime
                    with open(BOT_FILE, "r", encoding="utf-8") as f:
                        code = f.read()
                    if self.editor.get_code().strip() != code.strip():
                        self.editor.set_code(code)
                        self.log("🔄 [Hot-Reload] Обновлен bot.py!")
        except Exception:
            pass
        self.root.after(1000, self.check_file_changes)

    def render(self):
        self.canvas.delete("all")
        if not self.world: return
        w = self.world

        for x in range(0, W*TILE, TILE):
            self.canvas.create_line(x, 0, x, H*TILE, fill="#222")
        for y in range(0, H*TILE, TILE):
            self.canvas.create_line(0, y, W*TILE, y, fill="#222")

        for (wx, wy) in w.walls:
            x0, y0 = wx * TILE, wy * TILE
            self.canvas.create_rectangle(x0+2, y0+2, x0+TILE-2, y0+TILE-2, fill="#333", outline="#555", width=2)

        for r in w.resources.values():
            if r.amount <= 0: continue
            size = max(4, int(10 * r.amount / RESOURCE_AMOUNT))
            cx, cy = r.x * TILE + TILE // 2, r.y * TILE + TILE // 2
            self.canvas.create_oval(cx - size, cy - size, cx + size, cy + size, fill="#0c8", outline="#0a4", width=2)

        for core, color, label in ((w.player_core, "#39f", "P"), (w.enemy_core, "#f43", "E")):
            x0, y0 = core.x * TILE + 2, core.y * TILE + 2
            x1, y1 = core.x * TILE + TILE - 2, core.y * TILE + TILE - 2
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="#fff", width=2)
            self.canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=label, fill="#fff", font=("Helvetica", 14, "bold"))
            pct = max(0, core.hp) / CORE_HP
            self.canvas.create_rectangle(x0, y0 - 6, x0 + (x1 - x0) * pct, y0 - 2, fill="#0f0" if pct > 0.5 else "#ff0" if pct > 0.2 else "#f00", outline="")

        for u in w.units.values():
            cx, cy = u.x * TILE + TILE // 2, u.y * TILE + TILE // 2
            color = "#5af" if u.owner == "player" else "#f77"
            
            if u.kind == "worker":
                r = 8
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="#fff", width=2)
                if u.carry > 0:
                    self.canvas.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill="#0f0", outline="")
            elif u.kind == "soldier":
                self.canvas.create_rectangle(cx - 8, cy - 8, cx + 8, cy + 8, fill=color, outline="#fff", width=2)
            elif u.kind == "turret":
                self.canvas.create_polygon(cx, cy - 9, cx + 9, cy + 7, cx - 9, cy + 7, fill="#444", outline=color, width=3)
                self.canvas.create_oval(cx-3, cy-3, cx+3, cy+3, fill=color, outline="")
            
            maxhp = TURRET_HP if u.kind == "turret" else (WORKER_HP if u.kind == "worker" else SOLDIER_HP)
            pct = max(0, u.hp) / maxhp
            bx, by, bw = u.x * TILE + 4, u.y * TILE + 2, TILE - 8
            self.canvas.create_rectangle(bx, by, bx + bw, by + 3, fill="#500", outline="")
            self.canvas.create_rectangle(bx, by, bx + bw * pct, by + 3, fill="#0f0", outline="")

        p = w.player_core
        e = w.enemy_core
        self.status_var.set(f"Тик: {w.tick}   |   Энергия: {p.energy}   |   "
                            f"Юниты: {sum(1 for u in w.units.values() if u.owner=='player')}   |   "
                            f"HP ядра: {max(0,p.hp)} vs {max(0,e.hp)}")

        if e.hp <= 0:
            self.canvas.create_text(W*TILE/2, H*TILE/2, text="ВЫ ПОБЕДИЛИ!", fill="#0f0", font=("Helvetica", 28, "bold"))
        elif p.hp <= 0:
            self.canvas.create_text(W*TILE/2, H*TILE/2, text="ВЫ ПРОИГРАЛИ", fill="#f00", font=("Helvetica", 28, "bold"))
            
        # Восстанавливаем тултип, если мышка на месте
        self.current_tooltip = None

    def compile_bot(self):
        code = self.editor.get_code()
        try:
            with open(BOT_FILE, "w", encoding="utf-8") as f:
                f.write(code)
            self.last_mtime = os.path.getmtime(BOT_FILE)
        except Exception as e:
            self.log(f"❌ Ошибка сохранения: {e}")

        env = {"__builtins__": get_safe_builtins(self.log)}
        try:
            exec(compile(code, "<bot>", "exec"), env)
        except SyntaxError as e:
            self.log(f"❌ Синтаксическая ошибка в строке {e.lineno}: {e.msg}")
            return False
        except Exception as e:
            self.log(f"❌ Ошибка при компиляции: {e}")
            return False
            
        fn = env.get("tick")
        if fn is None:
            self.log("❌ Ошибка: в коде должна быть функция tick(state, api)")
            return False
        self.compiled_bot = fn
        return True

    def reload_bot(self):
        self.pause()
        if self.compile_bot():
            self.log("✅ Бот скомпилирован. Запуск...")
            self.run()

    def run(self):
        if self.world.player_core.hp <= 0 or self.world.enemy_core.hp <= 0:
            self.log("Игра окончена — нажмите Сброс.")
            return
        if not self.compiled_bot:
            if not self.compile_bot(): return
        self.running = True
        self.game_tick()

    def pause(self):
        self.running = False
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None

    def step_once(self):
        self.pause()
        if not self.compiled_bot:
            if not self.compile_bot(): return
        self.do_one_tick()

    def do_one_tick(self):
        if not self.world: return
        if self.world.player_core.hp <= 0 or self.world.enemy_core.hp <= 0:
            self.pause(); return
        
        player_actions = []
        try:
            state = State(self.world, "player", self.player_memory)
            api = API()
            self.compiled_bot(state, api)
            player_actions = api.actions
        except Exception as e:
            err = traceback.format_exc()
            self.log(f"❌ Ошибка выполнения:\n{err}")
            self.pause(); return

        enemy_actions = enemy_bot(self.world)
        self.world.step(player_actions, enemy_actions)
        self.render()

        if self.world.enemy_core.hp <= 0:
            self.log(f"🏆 Победа на тике {self.world.tick}!")
            self.pause()
        elif self.world.player_core.hp <= 0:
            self.log(f"💀 Поражение на тике {self.world.tick}.")
            self.pause()

    def game_tick(self):
        if not self.running: return
        self.do_one_tick()
        if self.running:
            self.after_id = self.root.after(self.delay_ms, self.game_tick)

    def reset(self):
        self.pause()
        self.world = World(seed=random.randint(1, 10**6))
        self.player_memory = {}
        self.compiled_bot = None
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")
        self.current_tooltip = None
        self.render()

def main():
    root = tk.Tk()
    Game(root)
    root.mainloop()

if __name__ == "__main__":
    main()