#!/usr/bin/env python3
# optimum_fc_full.py - FINAL: EXACT TEAM FILLING + EXTRA TEAMS
import os
import logging
from math import ceil
from random import shuffle
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# === Load .env ===
load_dotenv()

# === CONFIG ===
BOT_DISPLAY_NAME = "Optimum_Fc-Team_selector"
CREATOR = "4ce"
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN not found in .env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === In-memory state ===
chat_games: Dict[int, Dict[str, Any]] = {}

def get_game(chat_id: int) -> Dict[str, Any]:
    return chat_games.setdefault(chat_id, {
        "adding_names": False,
        "pending_name": None,
        "players": {"defender": [], "midfielder": [], "striker": []},
        "requested_teams": None,
        "players_per_team": None,
        "pos_quota": None,
        "awaiting": None,
    })

# === Keyboards ===
def make_position_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Defender", callback_data="assign_def"),
         InlineKeyboardButton("Midfielder", callback_data="assign_mid"),
         InlineKeyboardButton("Striker", callback_data="assign_str")]
    ])

def make_more_number_kb(prefix: str, options: List[int]) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(str(n), callback_data=f"{prefix}{n}") for n in options]
    row.append(InlineKeyboardButton("More +", callback_data=f"{prefix}more"))
    return InlineKeyboardMarkup([row])

def make_main_action_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Randomize", callback_data="action_randomize"),
         InlineKeyboardButton("Add player", callback_data="action_add"),
         InlineKeyboardButton("Remove player", callback_data="action_remove")],
        [InlineKeyboardButton("New game", callback_data="action_newgame")]
    ])

# === Team Allocation - FIXED: FILL MAIN TEAMS FIRST, THEN EXTRAS ===
def total_team_count(team: Dict[str, List[str]]) -> int:
    return sum(len(team.get(p, [])) for p in ("defender", "midfielder", "striker"))

def allocate_teams(
    players_dict: Dict[str, List[str]],
    requested_teams: int,
    players_per_team: int,
    pos_quota: Dict[str, int]
) -> tuple[List[Dict[str, List[str]]], Optional[str]]:

    # Make copies
    pool = {pos: players_dict[pos].copy() for pos in ("defender", "midfielder", "striker")}
    for pos in pool:
        shuffle(pool[pos])

    teams: List[Dict[str, List[str]]] = []
    extra_note = None

    # === STEP 1: Fill EXACTLY `requested_teams` with FULL quotas ===
    for team_idx in range(requested_teams):
        team = {"defender": [], "midfielder": [], "striker": []}
        for pos in ("defender", "midfielder", "striker"):
            needed = pos_quota.get(pos, 0)
            for _ in range(needed):
                if pool[pos]:
                    team[pos].append(pool[pos].pop(0))
                else:
                    break  # Not enough — but we still create team
        teams.append(team)

    # === STEP 2: Distribute ALL remaining players into NEW teams ===
    leftovers = []
    for pos in pool:
        leftovers.extend(pool[pos])

    if leftovers:
        shuffle(leftovers)
        extra_team = {"defender": [], "midfielder": [], "striker": []}
        for player in leftovers:
            # Try to assign by original position if possible
            assigned = False
            for pos in ("defender", "midfielder", "striker"):
                if player in players_dict[pos]:
                    extra_team[pos].append(player)
                    assigned = True
                    break
            if not assigned:
                extra_team["striker"].append(player)  # fallback
        teams.append(extra_team)
        extra_note = "*Extra team created for remaining players.*"

    return teams, extra_note

# === RENDER TEAMS - WITH YOUR EMOJIS ===
def render_teams(teams: List[Dict[str, List[str]]], note: Optional[str] = None) -> str:
    lines = ["Kick-off! Here are the teams:\n"]
    
    for idx, team in enumerate(teams, start=1):
        count = total_team_count(team)
        lines.append(f"<b>Team {idx}</b> — <i>{count} players</i>")
        lines.append(f"Defenders: {', '.join(team['defender']) if team['defender'] else '—'}")
        lines.append(f"Midfielders: {', '.join(team['midfielder']) if team['midfielder'] else '—'}")
        lines.append(f"Striker: {', '.join(team['striker']) if team['striker'] else '—'}")
        lines.append("")

    if note:
        lines.append(f"{note}\n")

    lines.append("<i>bot created by 4ce</i>")
    return "\n".join(lines)

# === Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Welcome to **{BOT_DISPLAY_NAME}**!\nUse /help to see commands.",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/newgame - Start adding players\n"
        "/done - Configure teams\n"
        "/status - View players\n"
        "/cancel - Reset session",
        parse_mode="Markdown"
    )

async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    g = get_game(chat_id)
    g.update({
        "adding_names": True, "pending_name": None,
        "players": {"defender": [], "midfielder": [], "striker": []},
        "requested_teams": None, "players_per_team": None, "pos_quota": None, "awaiting": None,
    })
    await update.message.reply_text("Send player names (one per message).\nUse /done when finished.")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    g = get_game(chat_id)
    g["adding_names"] = False
    await update.message.reply_text(
        "How many teams do you want?",
        reply_markup=make_more_number_kb("teams_", [2, 3, 4])
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    g = get_game(chat_id)
    p = g["players"]
    text = (
        f"<b>Defenders</b>: {', '.join(p['defender']) or '—'}\n"
        f"<b>Midfielders</b>: {', '.join(p['midfielder']) or '—'}\n"
        f"<b>Strikers</b>: {', '.join(p['striker']) or '—'}"
    )
    await update.message.reply_text(text or "No players yet.", parse_mode="HTML")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_games.pop(chat_id, None)
    await update.message.reply_text("Session cancelled.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    g = get_game(chat_id)
    text = update.message.text.strip()

    if g.get("awaiting"):
        try:
            n = int(text)
        except:
            await update.message.reply_text("Please send a valid number.")
            return

        tag = g["awaiting"]
        if tag == "teams_more" and n >= 1:
            g["requested_teams"] = n
            g["awaiting"] = None
            await update.message.reply_text("Players per team?", reply_markup=make_more_number_kb("ppt_", [5,6,7]))
        elif tag == "ppt_more" and n >= 1:
            g["players_per_team"] = n
            g["awaiting"] = None
            await update.message.reply_text("Defenders per team?", reply_markup=make_more_number_kb("quota_def_", [3,4]))
        elif tag in ("quota_def_more", "quota_mid_more", "quota_str_more"):
            pos_map = {"def": "defender", "mid": "midfielder", "str": "striker"}
            pos_key = tag.split("_")[1]
            pos = pos_map[pos_key]
            if n >= 0:
                g.setdefault("pos_quota", {})[pos] = n
                g["awaiting"] = None
                if pos == "defender":
                    await update.message.reply_text("Midfielders per team?", reply_markup=make_more_number_kb("quota_mid_", [2,3]))
                elif pos == "midfielder":
                    await update.message.reply_text("Strikers per team?", reply_markup=make_more_number_kb("quota_str_", [1,2]))
                else:
                    await update.message.reply_text("Quotas set!", reply_markup=make_main_action_kb())
            return

    if g.get("adding_names") and text:
        g["pending_name"] = text
        await update.message.reply_text(
            f"Assign position for <b>{text}</b>:",
            parse_mode="HTML",
            reply_markup=make_position_kb()
        )
        return

    await update.message.reply_text("Unknown command. Use /help.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    g = get_game(chat_id)
    data = query.data

    if data in ("assign_def", "assign_mid", "assign_str"):
        if not g.get("pending_name"):
            await query.edit_message_text("No name pending.")
            return
        name = g["pending_name"]
        pos_map = {
            "assign_def": ("defender", "Defender"),
            "assign_mid": ("midfielder", "Midfielder"),
            "assign_str": ("striker", "Striker"),
        }
        pos, role = pos_map[data]
        g["players"][pos].append(name)
        g["pending_name"] = None
        await query.edit_message_text(f"<b>{name}</b> → {role}", parse_mode="HTML")
        return

    if data.startswith(("teams_", "ppt_", "quota_def_", "quota_mid_", "quota_str_")):
        if data.endswith("more"):
            g["awaiting"] = data.replace("more", "more")
            await query.edit_message_text(f"Type number for {data.split('_')[0] + 's'}:")
            return
        try:
            val = int(data.split("_")[-1])
        except:
            await query.edit_message_text("Invalid.")
            return

        if data.startswith("teams_"):
            g["requested_teams"] = val
            await query.edit_message_text("Players per team?", reply_markup=make_more_number_kb("ppt_", [5,6,7]))
        elif data.startswith("ppt_"):
            g["players_per_team"] = val
            g["pos_quota"] = {}
            await query.edit_message_text("Defenders per team?", reply_markup=make_more_number_kb("quota_def_", [3,4]))
        else:
            pos_map = {"def": "defender", "mid": "midfielder", "str": "striker"}
            pos_key = data.split("_")[1]
            pos = pos_map[pos_key]
            g.setdefault("pos_quota", {})[pos] = val
            next_step = {
                "defender": ("Midfielders per team?", "quota_mid_", [2,3]),
                "midfielder": ("Strikers per team?", "quota_str_", [1,2]),
                "striker": ("Quotas set!", None, None),
            }
            msg, prefix, opts = next_step[pos]
            if prefix:
                await query.edit_message_text(f"{pos.capitalize()}: {val}. {msg}", reply_markup=make_more_number_kb(prefix, opts))
            else:
                await query.edit_message_text(msg, reply_markup=make_main_action_kb())
        return

    if data == "action_randomize":
        if not all([g.get("requested_teams"), g.get("players_per_team"), g.get("pos_quota")]):
            await query.answer("Complete setup first.", show_alert=True)
            return

        players_copy = {k: v.copy() for k, v in g["players"].items()}
        teams, note = allocate_teams(
            players_copy,
            g["requested_teams"],
            g["players_per_team"],
            g["pos_quota"]
        )
        if not teams:
            await query.message.reply_text("No players.")
            return

        out = render_teams(teams, note)
        await query.message.reply_text(out, parse_mode="HTML")
        await query.message.reply_text(
            "Choose:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Randomize again", callback_data="action_randomize"),
                 InlineKeyboardButton("New game", callback_data="action_newgame")]
            ])
        )
        return

    if data == "action_add":
        g["adding_names"] = True
        await query.message.reply_text("Add mode ON — send player names.")
        return

    if data == "action_remove":
        players = [(p, pos) for pos in g["players"] for p in g["players"][pos]]
        if not players:
            await query.answer("No players to remove.", show_alert=True)
            return
        kb = [[InlineKeyboardButton(f"Remove {name} ({pos})", callback_data=f"remove_{pos}|{name.replace('|',' ')}")] for name, pos in players]
        kb.append([InlineKeyboardButton("Cancel", callback_data="remove_cancel")])
        await query.message.reply_text("Remove player:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("remove_"):
        if data == "remove_cancel":
            await query.edit_message_text("Cancelled.")
            return
        try:
            _, rest = data.split("_", 1)
            pos, name = rest.split("|", 1)
        except:
            await query.answer("Error.", show_alert=True)
            return
        if name in g["players"].get(pos, []):
            g["players"][pos].remove(name)
            await query.edit_message_text(f"Removed <b>{name}</b> from {pos}.", parse_mode="HTML")
        return

    if data == "action_newgame":
        g.update({
            "adding_names": True, "pending_name": None,
            "players": {"defender": [], "midfielder": [], "striker": []},
            "requested_teams": None, "players_per_team": None, "pos_quota": None, "awaiting": None,
        })
        await query.message.reply_text("New game started! Send player names.")

# === Main ===
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print(f"{BOT_DISPLAY_NAME} is running. Creator: {CREATOR}")
    app.run_polling()

if __name__ == "__main__":
    main()