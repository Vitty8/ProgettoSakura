import logging
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from text import get_benvenuto_popolare_text, get_benvenuto_tecnica_text, get_benvenuto_prop_text, welcome_text
from profili import artists
import asyncio
from dotenv import load_dotenv
from aiohttp import web
import cloudinary
import cloudinary.uploader
import firebase_admin
from firebase_admin import credentials, db
from typing import Dict, List, Tuple

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
PORT = int(os.getenv('PORT', 8443))
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.environ["WEBHOOK_URL"].rstrip("/")
WEBHOOK_PATH = f"{TOKEN}"
FULL_WEBHOOK = f"{WEBHOOK_URL}/{WEBHOOK_PATH}"

# Aggiungi debug logging per verificare la configurazione
logger.info(f"TOKEN: {TOKEN[:10]}...")  # Mostra solo i primi 10 caratteri per sicurezza
logger.info(f"WEBHOOK_URL: {WEBHOOK_URL}")
logger.info(f"WEBHOOK_PATH: {WEBHOOK_PATH}")
logger.info(f"FULL_WEBHOOK: {FULL_WEBHOOK}")

# Cloudinary Configuration
cloudinary.config(
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
  api_key = os.getenv("CLOUDINARY_API_KEY"),
  api_secret = os.getenv("CLOUDINARY_API_SECRET")
)

# Stati della ConversationHandler
# Stati principali
MAIN_MENU = 0
PASSWORD = 1
VOTE = 2

# Stati per le impostazioni
SET_OPTION = 10  
SET_DETAIL = 11      
SET_VALUE = 12       
SET_HOME_PICTURE = 13
# Stati per la gestione artisti
ARTISTI_CHOICE = 20
ARTISTI_ADD_NAME = 31
ARTISTI_ADD_AGE = 32
ARTISTI_ADD_PHOTO = 33
ARTISTI_ADD_SONG = 34
ARTISTI_ADD_CATEGORY = 35
ARTISTI_REMOVE = 22

# Password (consider moving to bot_data for dynamic changes)
PASSWORD_POPOLARE = "1234"
PASSWORD_TECNICA = "5678"
PASSWORD_OWNER = "9999"

TECHNICAL_AMBITI = ["Intonazione", "Interpretazione", "Tecninca Musicale/Strumentale", "Presenza Scenica"]

cred = credentials.Certificate(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

firebase_admin.initialize_app(cred, {
    'databaseURL': os.getenv("FIREBASE_DATABASE_URL")
})


def get_public_id_from_url(url: str) -> str:
    """Extracts the public_id from a Cloudinary URL."""
    try:
        parts = url.split('/')
        upload_index = parts.index('upload')
        public_id_with_ext = '/'.join(parts[upload_index+2:])
        public_id = os.path.splitext(public_id_with_ext)[0]
        return public_id
    except (ValueError, IndexError):
        return None

def sanitize_votes_tecnica(votes_tecnica: dict) -> dict:
    clean = {}
    for artist_key, users in votes_tecnica.items():
        clean[artist_key] = {}
        for user_id, aspects in users.items():
            clean_aspects = {
                ambito.replace('/', '_'): score
                for ambito, score in aspects.items()
            }
            clean[artist_key][user_id] = clean_aspects
    return clean

def save_bot_data(bot_data: dict) -> None:
    data_to_save = {
        "max_judges_popolare": bot_data.get("max_judges_popolare"),
        "max_judges_tecnica": bot_data.get("max_judges_tecnica"),
        "home_picture_url": bot_data.get("home_picture_url"),
        "votes_popolare": bot_data.get("votes_popolare", {}),
        # sanifichiamo i nomi degli ambiti tecnici
        "votes_tecnica": sanitize_votes_tecnica(bot_data.get("votes_tecnica", {})),
        "judges_popolare": list(bot_data.get("judges_popolare", [])),
        "judges_tecnica": list(bot_data.get("judges_tecnica", [])),
        "judge_types": bot_data.get("judge_types", {}),
        "password_popolare": PASSWORD_POPOLARE,
        "password_tecnica": PASSWORD_TECNICA,
        "password_owner": PASSWORD_OWNER,
        "owners_ids": list(bot_data.get("owners_ids", []))
    }
    try:
        ref = db.reference('bot_data')
        ref.set(data_to_save)
    except Exception as e:
        logger.error(f"Errore nel salvataggio dei dati su Firebase: {e}")

def load_bot_data() -> dict:
    try:
        ref = db.reference('bot_data')
        data = ref.get()
        if not data:
            return {}
        data["judges_popolare"] = set(data.get("judges_popolare", []))
        data["judges_tecnica"] = set(data.get("judges_tecnica", []))
        data["owners_ids"] = set(data.get("owners_ids", []))
        return data
    except Exception as e:
        logger.error(f"Errore nel caricamento dei dati da Firebase: {e}")
        return {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Invia un messaggio di benvenuto leggendo l'URL dell'immagine da bot_data."""
    if context.user_data.get("logged_in"):
        await update.message.reply_text(
            "_⏸️ Sei già autenticato\\. Se desideri effettuare una nuova autenticazione, premi /logout\\._", 
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return MAIN_MENU

    home_pic_url = context.bot_data.get("home_picture_url")
    welcome_message_text = welcome_text(update)

    if home_pic_url:
        try:
            # Prova a inviare la foto dall'URL salvato
            await update.message.reply_photo(
                photo=home_pic_url,
                caption=welcome_message_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            # Se l'URL non è valido o c'è un errore, invia solo il testo
            logger.error(f"Impossibile inviare foto home dall'URL {home_pic_url}: {e}")
            await update.message.reply_text(
                text=welcome_message_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
    else:
        # Se nessun URL è configurato, invia solo il testo
        logger.info("Nessuna home_picture_url configurata. Invio del solo testo.")
        await update.message.reply_text(
            text=welcome_message_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )

    return PASSWORD

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global PASSWORD_POPOLARE, PASSWORD_TECNICA, PASSWORD_OWNER
    user_password = update.message.text.strip()
    
    if user_password == PASSWORD_POPOLARE:
        context.user_data['jury_type'] = "popolare"
        context.user_data["logged_in"] = True 
        judges_popolare = context.bot_data.setdefault("judges_popolare", set())
        max_limit = context.bot_data.get("max_judges_popolare")
        if max_limit and len(judges_popolare) >= max_limit:
            await update.message.reply_text("_⚠️ È stato raggiunto il limite di componenti della giuria popolare\\!_", parse_mode=ParseMode.MARKDOWN_V2)
            return ConversationHandler.END
        judges_popolare.add(update.effective_chat.id)
        context.bot_data["judges_popolare"] = judges_popolare
        context.bot_data.setdefault("votes_popolare", {})
        await update.message.reply_text(get_benvenuto_popolare_text(update), parse_mode=ParseMode.MARKDOWN_V2)
        await notify_owner(update, context, "popolare")
        save_bot_data(context.bot_data)
        return VOTE

    elif user_password == PASSWORD_TECNICA:
        context.user_data['jury_type'] = "tecnica"
        context.user_data["logged_in"] = True
        judges_tecnica = context.bot_data.setdefault("judges_tecnica", set())
        max_limit = context.bot_data.get("max_judges_tecnica")
        if max_limit and len(judges_tecnica) >= max_limit:
            await update.message.reply_text("_⚠️ È stato raggiunto il limite di componenti della giuria tecnica\\!_", parse_mode=ParseMode.MARKDOWN_V2)
            return ConversationHandler.END
        judges_tecnica.add(update.effective_chat.id)
        context.bot_data["judges_tecnica"] = judges_tecnica
        context.bot_data.setdefault("votes_tecnica", {})
        judge_types = context.bot_data.setdefault("judge_types", {})
        judge_types[update.effective_chat.id] = "tecnica"
        await update.message.reply_text(get_benvenuto_tecnica_text(update), parse_mode=ParseMode.MARKDOWN_V2)
        await notify_owner(update, context, "tecnica")
        save_bot_data(context.bot_data)
        return VOTE

    elif user_password == PASSWORD_OWNER:
        owners_ids = context.bot_data.setdefault("owners_ids", set())
        if len(owners_ids) >= 3 and update.effective_chat.id not in owners_ids:
            await update.message.reply_text("_⚠️ È stato raggiunto il limite di proprietari\\! Attendi che qualcuno effettui il logout\\._", parse_mode=ParseMode.MARKDOWN_V2)
            return ConversationHandler.END
        
        context.user_data['user_role'] = "owner"
        context.user_data["logged_in"] = True
        owners_ids.add(update.effective_chat.id)
        context.bot_data["owners_ids"] = owners_ids
        save_bot_data(context.bot_data)
        await update.message.reply_text(get_benvenuto_prop_text(update), parse_mode=ParseMode.MARKDOWN_V2)
        return MAIN_MENU
    else:
        await update.message.reply_text("_⚠️ Password non valida\\! Riprova\\._", parse_mode=ParseMode.MARKDOWN_V2)
        return PASSWORD

async def notify_owner(update: Update, context: ContextTypes.DEFAULT_TYPE, jury_type: str) -> None:
    owners_ids = context.bot_data.get("owners_ids", set())
    if not owners_ids:
        return
        
    user_name = update.effective_user.first_name
    escape_username = escape_markdown(user_name, version=2)
    user_id = update.effective_chat.id
    clickable_name = f"[{escape_username}](tg://user?id={user_id})"
    text = f"_👤 Il giudice {clickable_name} si è registrato come giuria di tipo *{jury_type}*\\._"
    
    for owner_id in owners_ids:
        try:
            await context.bot.send_message(chat_id=owner_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.error(f"Errore nell'invio della notifica al proprietario {owner_id}: {e}")

async def votazioni_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    owners_ids = context.bot_data.get("owners_ids", set())
    if update.effective_chat.id not in owners_ids:
        await update.message.reply_text("Non sei autorizzato ad eseguire questo comando.")
        return MAIN_MENU
    await send_owner_buttons(update, context)
    return MAIN_MENU

async def send_owner_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    artists_data = context.bot_data['artists']
    buttons = []
    row = []
    for i, (key, artist) in enumerate(artists_data.items()):
        row.append(InlineKeyboardButton(artist['nome'], callback_data=key))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🛑 Interrompi votazioni", callback_data="stop_voting")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text(
        text="*Che le votazioni abbiano inizio\\!*\n\n_Premi sul nome dell'artista per il quale vuoi che venga espresso il voto della giuria\\._" ,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def owner_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    artist_key = query.data

    if artist_key == "stop_voting":
        await stop_voting_handler(update, context)
        return MAIN_MENU

    artists = context.bot_data.get("artists", {})
    if artist_key not in artists:
        await query.edit_message_text("Artista non trovato.")
        return MAIN_MENU

    artist = artists[artist_key]
    await query.message.reply_text(
        f"*🔜 Cominciano le votazioni per {artist['nome']}*",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    context.bot_data["current_selected_artist"] = artist_key

    response_text = (
        f"*Nome:* {escape_markdown(artist['nome'], version=2)}\n"
        f"*Età:* {artist['età']}\n"
        f"*Canzone:* {escape_markdown(artist['canzone'], version=2)}"
    )
    
    judges = set()
    judges.update(context.bot_data.get("judges_popolare", set()))
    judges.update(context.bot_data.get("judges_tecnica", set()))
    judge_types = context.bot_data.get("judge_types", {})

    for judge_chat_id in judges:
        try:
            prompt = "\n\n_🔽 Inserisci il tuo voto per questo artista\\:_"
            if judge_types.get(judge_chat_id) == "tecnica":
                prompt = f"\n\n_🔽 Esprimi il tuo voto per la categoria *{TECHNICAL_AMBITI[0]}*\\._"

            if artist.get('foto'):
                await context.bot.send_photo(
                    chat_id=judge_chat_id,
                    photo=artist['foto'],
                    caption=response_text + prompt,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await context.bot.send_message(
                    chat_id=judge_chat_id,
                    text=response_text + prompt,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        except Exception as e:
            logger.error(f"Errore nell'invio del profilo all'utente {judge_chat_id}: {e}")

    return VOTE # Remain in VOTE state to receive votes

async def vote_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "current_selected_artist" not in context.bot_data:
        await update.message.reply_text("Nessun artista selezionato, attendi che il proprietario lo scelga.")
        return VOTE

    current_artist = context.bot_data["current_selected_artist"]
    user_id = update.effective_user.id
    vote_input_str = update.message.text.strip()
    try:
        vote_value = float(vote_input_str)
    except ValueError:
        await update.message.reply_text("❌ Inserisci un numero valido per il voto.")
        return VOTE

    jury_type = context.user_data.get('jury_type', 'popolare')

    if jury_type == "popolare":
        votes_dict = context.bot_data.setdefault("votes_popolare", {})
        if current_artist not in votes_dict:
            votes_dict[current_artist] = {}
        if user_id in votes_dict[current_artist]:
            await update.message.reply_text("🔚 Hai già votato per questo artista\\!")
            return VOTE
        
        if not 1 <= vote_value <= 10:
            await update.message.reply_text("#️⃣ Il voto deve essere compreso tra 1 e 10\\. Riprova\\.")
            return VOTE

        votes_dict[current_artist][user_id] = vote_value
        await update.message.reply_text("Grazie per il tuo voto!")
        
        owners_ids = context.bot_data.get("owners_ids", set())
        if owners_ids:
            user_name = update.effective_user.first_name
            escape_username = escape_markdown(user_name, version=2)
            clickable_name = f"[{escape_username}](tg://user?id={user_id})"
            formatted_vote = escape_markdown(str(vote_value), version=2)
            artist_nome = escape_markdown(context.bot_data['artists'][current_artist]['nome'], version=2)
            notification_text = (
                f"🔝 Il giudice {clickable_name} ha votato per l'artista {artist_nome} con voto\\: {formatted_vote}\\."
            )
            for owner_id in owners_ids:
                try:
                    await context.bot.send_message(chat_id=owner_id, text=notification_text, parse_mode=ParseMode.MARKDOWN_V2)
                except Exception as e:
                    logger.error(f"Errore nell'invio della notifica al proprietario {owner_id}: {e}")
        save_bot_data(context.bot_data)
        return VOTE

    else: # Technical Jury
        votes_dict = context.bot_data.setdefault("votes_tecnica", {})
        if current_artist not in votes_dict:
            votes_dict[current_artist] = {}
        if user_id not in votes_dict[current_artist]:
            votes_dict[current_artist][user_id] = {}

        ambito_index = context.user_data.get("ambito_index", 0)
        current_ambito = TECHNICAL_AMBITI[ambito_index]

        if not 1 <= vote_value <= 10:
            await update.message.reply_text(
                f"#️⃣ Il voto per la categoria *{current_ambito}* deve essere compreso tra 1 e 10\\. Riprova\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return VOTE

        if current_ambito in votes_dict[current_artist][user_id]:
            await update.message.reply_text("🔚 Hai già votato per questo artista in questo ambito\\!")
            return VOTE

        votes_dict[current_artist][user_id][current_ambito] = vote_value
        ambito_index += 1
        context.user_data["ambito_index"] = ambito_index

        if ambito_index < len(TECHNICAL_AMBITI):
            next_ambito = TECHNICAL_AMBITI[ambito_index]
            await update.message.reply_text(
                f"_🔽 Esprimi il tuo voto per la categoria *{next_ambito}*\\._",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            user_votes = votes_dict[current_artist][user_id]
            total = sum(user_votes.values())
            avg = total / len(TECHNICAL_AMBITI)
            avg2 = escape_markdown(f"{avg:.2f}", version=2)
            await update.message.reply_text(
                f"*🆒 Grazie per il tuo voto\\! La media dei voti è\\: {avg2}*",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
            owners_ids = context.bot_data.get("owners_ids", set())
            if owners_ids:
                user_name = update.effective_user.first_name
                escape_username = escape_markdown(user_name, version=2)
                clickable_name = f"[{escape_username}](tg://user?id={user_id})"
                artist_nome = escape_markdown(context.bot_data['artists'][current_artist]['nome'], version=2)
                notification_text = (
                    f"🔝 Il giudice {clickable_name} ha votato per l'artista {artist_nome}\\. Media dei voti\\: {avg2}"
                )
                for owner_id in owners_ids:
                    try:
                        await context.bot.send_message(chat_id=owner_id, text=notification_text, parse_mode=ParseMode.MARKDOWN_V2)
                    except Exception as e:
                        logger.error(f"Errore nell'invio della notifica al proprietario {owner_id}: {e}")
            context.user_data["ambito_index"] = 0 # Reset for next artist
        
        save_bot_data(context.bot_data)
        return VOTE

async def stop_voting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    artists_data: Dict[str, dict] = context.bot_data.get("artists", {})
    votes_popolare: Dict[str, Dict[int, int]] = context.bot_data.get("votes_popolare", {})
    votes_tecnica: Dict[str, Dict[int, Dict[str, int]]] = context.bot_data.get("votes_tecnica", {})

    ranking: Dict[str, List[Tuple[float, str, float, float]]] = {}

    for artist_key, artist in artists_data.items():
        categoria = artist.get("categoria", "Giovani Promesse")

        pop_votes = votes_popolare.get(artist_key, {})
        avg_pop = sum(pop_votes.values()) / len(pop_votes) if pop_votes else 0.0

        tech_votes = votes_tecnica.get(artist_key, {})
        tech_list = [sum(aspects.values()) / len(aspects) for aspects in tech_votes.values() if aspects]
        avg_tech = sum(tech_list) / len(tech_list) if tech_list else 0.0

        overall_avg = (avg_pop + avg_tech) / 2
        nome_esc = escape_markdown(artist.get("nome", ""), version=2)

        ranking.setdefault(categoria, []).append((overall_avg, nome_esc, avg_pop, avg_tech))

    for entries in ranking.values():
        entries.sort(key=lambda x: x[0], reverse=True)

    parts = ["*🏆 Risultati Votazioni:*"]
    for categoria, entries in ranking.items():
        if not entries:
            continue
        cat_esc = escape_markdown(categoria, version=2)
        parts.append(f"\n*Categoria: {cat_esc}*")
        for overall, nome, pop_m, tech_m in entries:
            overall_str = escape_markdown(f"{overall:.2f}", version=2)
            pop_str = escape_markdown(f"{pop_m:.2f}", version=2)
            tech_str = escape_markdown(f"{tech_m:.2f}", version=2)
            parts.append(
                f"*{nome}: {overall_str}*\n"
                f"\\- Popolare: {pop_str}\n"
                f"\\- Tecnica: {tech_str}\n"
            )
    message = "\n".join(parts)

    for owner_id in context.bot_data.get("owners_ids", set()):
        try:
            await context.bot.send_message(chat_id=owner_id, text=message, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.error(f"Errore nell'invio dei risultati al proprietario: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operazione annullata. Usa /start per riprovare.")
    return ConversationHandler.END

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get("logged_in"):
        context.user_data.pop("logged_in")
    
    if context.user_data.get("user_role") == "owner":
        owners_ids = context.bot_data.get("owners_ids", set())
        if update.effective_chat.id in owners_ids:
            owners_ids.remove(update.effective_chat.id)
            context.bot_data["owners_ids"] = owners_ids
        context.user_data.pop("user_role", None)
        save_bot_data(context.bot_data)
    
    await update.message.reply_text("_🆓 Hai effettuato il logout\\. Usa /start per reinserire la password\\._", parse_mode=ParseMode.MARKDOWN_V2)
    return ConversationHandler.END

def main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("⚖️ Numero Giudici", callback_data="set_judges"),
            InlineKeyboardButton("⚙️ Password", callback_data="set_passwords")
        ],
        [InlineKeyboardButton("🖼️ Immagine Home", callback_data="set_home_picture")], # <-- NUOVO PULSANTE
        [InlineKeyboardButton("🗑 Chiudi", callback_data="close_keyboard")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def set_limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    owners_ids = context.bot_data.get("owners_ids", set())
    if update.effective_chat.id not in owners_ids:
        await update.message.reply_text("Non sei autorizzato ad eseguire questo comando.")
        return MAIN_MENU

    await update.message.reply_text(
        "*ℹ️ Seleziona l'impostazione che vuoi modificare\\:*",
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN_V2
    )
    return SET_OPTION

async def close_keyboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.delete_message()
    return MAIN_MENU

async def set_option_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "set_judges":
        keyboard = [
            [
                InlineKeyboardButton("👥 Giuria Popolare", callback_data="set_limit_popolare"),
                InlineKeyboardButton("🗣 Giuria Tecnica", callback_data="set_limit_tecnica")
            ],
            [InlineKeyboardButton("🔙 Indietro", callback_data="back_to_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "*🛃 Seleziona il tipo di giuria per cui impostare il numero di giudici\\:*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return SET_DETAIL

    elif data == "set_passwords":
        keyboard = [
            [InlineKeyboardButton("1️⃣ Password Giuria Popolare", callback_data="set_pass_popolare")],
            [InlineKeyboardButton("2️⃣ Password Giuria Tecnica", callback_data="set_pass_tecnica")],
            [InlineKeyboardButton("3️⃣ Password Owner", callback_data="set_pass_owner")],
            [InlineKeyboardButton("🔙 Indietro", callback_data="back_to_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "*🛃 Seleziona la password che vuoi modificare\\:*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return SET_DETAIL
    
    elif data == "set_home_picture": # <-- NUOVA CONDIZIONE
        await query.edit_message_text(
            "_🖼️ Invia la nuova immagine di benvenuto che vuoi impostare\\._",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return SET_HOME_PICTURE

async def set_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ["set_limit_popolare", "set_limit_tecnica"]:
        context.user_data["limit_type"] = "popolare" if data == "set_limit_popolare" else "tecnica"
        await query.edit_message_text(
            f"*🛃 Inserisci il nuovo limite per la giuria {context.user_data['limit_type']}\\:*",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return SET_VALUE

    elif data in ["set_pass_popolare", "set_pass_tecnica", "set_pass_owner"]:
        context.user_data["pass_type"] = {
            "set_pass_popolare": "popolare",
            "set_pass_tecnica": "tecnica",
            "set_pass_owner": "owner"
        }[data]
        await query.edit_message_text(
            f"*🛃 Inserisci la nuova password per {context.user_data['pass_type']}\\:*",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return SET_VALUE

    elif data == "back_to_main_menu":
        await query.edit_message_text(
            "*ℹ️ Seleziona l'impostazione che vuoi modificare\\:*",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return SET_OPTION

async def set_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_value = update.message.text.strip()
    keyboard = []

    if "limit_type" in context.user_data:
        try:
            new_limit = int(new_value)
            limit_type = context.user_data.pop("limit_type")
            if limit_type == "popolare":
                context.bot_data["max_judges_popolare"] = new_limit
            elif limit_type == "tecnica":
                context.bot_data["max_judges_tecnica"] = new_limit

            message_text = f"_✅ Limite per la giuria {limit_type} impostato a {new_limit}\\._"
            keyboard = [[InlineKeyboardButton("🔙 Indietro", callback_data="back_to_limit_menu")]]
        except ValueError:
            await update.message.reply_text("Inserisci un numero valido.")
            return SET_VALUE

    elif "pass_type" in context.user_data:
        global PASSWORD_POPOLARE, PASSWORD_TECNICA, PASSWORD_OWNER
        pass_type = context.user_data.pop("pass_type")
        if pass_type == "popolare":
            PASSWORD_POPOLARE = new_value
        elif pass_type == "tecnica":
            PASSWORD_TECNICA = new_value
        elif pass_type == "owner":
            PASSWORD_OWNER = new_value

        message_text = f"_✅ Nuova password per {pass_type} impostata correttamente\\._"
        keyboard = [[InlineKeyboardButton("🔙 Indietro", callback_data="back_to_password_menu")]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    save_bot_data(context.bot_data)  
    return SET_VALUE

async def set_home_picture_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce il caricamento della nuova immagine di benvenuto."""
    if not update.message.photo:
        await update.message.reply_text("Per favore, invia una foto valida.")
        return SET_HOME_PICTURE

    
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    try:
        # Carica la nuova immagine su Cloudinary in una cartella dedicata
        upload_result = cloudinary.uploader.upload(file.file_path, folder="home_pictures")
        new_photo_url = upload_result.get("secure_url")

        if not new_photo_url:
            raise ValueError("Caricamento su Cloudinary fallito, nessun URL restituito.")

        # Se esiste una vecchia immagine, eliminala da Cloudinary
        old_photo_url = context.bot_data.get("home_picture_url")
        if old_photo_url:
            public_id = get_public_id_from_url(old_photo_url)
            if public_id:
                try:
                    cloudinary.uploader.destroy(public_id)
                    logger.info(f"Vecchia immagine home ({public_id}) eliminata da Cloudinary.")
                except Exception as e:
                    logger.error(f"Errore eliminazione vecchia immagine home da Cloudinary: {e}")

        # Salva il nuovo URL e aggiorna il database
        context.bot_data["home_picture_url"] = new_photo_url
        save_bot_data(context.bot_data)

        await update.message.reply_text(
            "_✅ Immagine di benvenuto aggiornata con successo\\!_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Ritorna al menu delle impostazioni per una migliore esperienza utente
        await set_limit_command(update, context)
        return SET_OPTION

    except Exception as e:
        logger.error(f"Errore durante l'upload della home picture: {e}")
        await update.message.reply_text("Si è verificato un errore durante il caricamento. Riprova.")
        return SET_HOME_PICTURE
    
async def back_to_password_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("1️⃣ Password Giuria Popolare", callback_data="set_pass_popolare")],
        [InlineKeyboardButton("2️⃣ Password Giuria Tecnica", callback_data="set_pass_tecnica")],
        [InlineKeyboardButton("3️⃣ Password Owner", callback_data="set_pass_owner")],
        [InlineKeyboardButton("🔙 Indietro", callback_data="back_to_main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "*🛃 Seleziona la password che vuoi modificare:*",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    return SET_DETAIL

async def back_to_limit_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [
            InlineKeyboardButton("👥 Giuria Popolare", callback_data="set_limit_popolare"),
            InlineKeyboardButton("🗣 Giuria Tecnica", callback_data="set_limit_tecnica")
        ],
        [InlineKeyboardButton("🔙 Indietro", callback_data="back_to_main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "*🛃 Seleziona il tipo di giuria per cui impostare il numero di giudici:*",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    return SET_DETAIL

async def reset_voting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    owners_ids = context.bot_data.get("owners_ids", set())
    if update.effective_chat.id not in owners_ids:
        await update.message.reply_text("Non sei autorizzato ad eseguire questo comando.")
        return MAIN_MENU

    context.bot_data["votes_popolare"] = {}
    context.bot_data["votes_tecnica"] = {}
    context.bot_data["judges_popolare"] = set()
    context.bot_data["judges_tecnica"] = set()
    context.bot_data["judge_types"] = {}

    save_bot_data(context.bot_data)
    await update.message.reply_text("✅ I dati sono stati eliminati.")
    return MAIN_MENU

async def artisti_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    owners_ids = context.bot_data.get("owners_ids", set())
    if update.effective_chat.id not in owners_ids:
        await update.message.reply_text("Non sei autorizzato ad eseguire questo comando.")
        return MAIN_MENU

    keyboard = [
        [InlineKeyboardButton("➕ Aggiungi Artista", callback_data="add_artist")],
        [InlineKeyboardButton("➖ Rimuovi Artista", callback_data="remove_artist")],
        [InlineKeyboardButton("✖️ Annulla", callback_data="cancel_artists")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Seleziona l'azione da eseguire:", reply_markup=reply_markup)
    return ARTISTI_CHOICE

async def artisti_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "add_artist":
        context.user_data["new_artist"] = {}
        await query.edit_message_text("_🔤 Inserisci il *nome* dell'artista\\:_", parse_mode=ParseMode.MARKDOWN_V2)
        return ARTISTI_ADD_NAME

    elif choice == "remove_artist":
        artists = context.bot_data.get("artists", {})
        if not artists:
            await query.edit_message_text("Non ci sono artisti da rimuovere.")
            return MAIN_MENU

        keyboard = [[InlineKeyboardButton(artist['nome'], callback_data=f"rm_{key}")] for key, artist in artists.items()]
        keyboard.append([InlineKeyboardButton("✖️ Annulla", callback_data="cancel_artists")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("_Seleziona l'artista da rimuovere\\:_", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        return ARTISTI_REMOVE

    elif choice == "cancel_artists":
        await query.edit_message_text("Operazione annullata.")
        return MAIN_MENU

async def add_artist_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome = update.message.text.strip()
    context.user_data["new_artist"]["nome"] = nome
    await update.message.reply_text("_🔢 Inserisci l'*età* dell'artista\\:_", parse_mode=ParseMode.MARKDOWN_V2)
    return ARTISTI_ADD_AGE

async def add_artist_age_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    eta_str = update.message.text.strip()
    try:
        eta = int(eta_str)
        context.user_data["new_artist"]["età"] = eta
        await update.message.reply_text("_🎦 Invia la *foto* dell'artista\\:_", parse_mode=ParseMode.MARKDOWN_V2)
        return ARTISTI_ADD_PHOTO
    except ValueError:
        await update.message.reply_text("L'età deve essere un numero intero. Riprova:")
        return ARTISTI_ADD_AGE

async def add_artist_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo:
        await update.message.reply_text("Per favore, invia una foto valida.")
        return ARTISTI_ADD_PHOTO

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    try:
        upload_result = cloudinary.uploader.upload(file.file_path, folder="artist_photos")
        photo_url = upload_result.get("secure_url")
        if not photo_url:
            raise ValueError("Cloudinary did not return a secure_url")
        context.user_data["new_artist"]["foto"] = photo_url
        await update.message.reply_text("_🎵 Inserisci il *titolo della canzone*\\._", parse_mode=ParseMode.MARKDOWN_V2)
        return ARTISTI_ADD_SONG
    except Exception as e:
        logger.error(f"Errore durante l'upload su Cloudinary: {e}")
        await update.message.reply_text("Si è verificato un errore durante il caricamento dell'immagine. Riprova.")
        return ARTISTI_ADD_PHOTO

async def add_artist_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    canzone = update.message.text.strip()
    context.user_data["new_artist"]["canzone"] = canzone
    keyboard = [
        [
            InlineKeyboardButton("Giovani Promesse", callback_data="categoria_giovani_promesse"),
            InlineKeyboardButton("Sogno nel cassetto", callback_data="categoria_sogno_nel_cassetto")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("_Seleziona la categoria dell'artista\\:_", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return ARTISTI_ADD_CATEGORY

async def add_artist_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    categoria = " ".join(query.data.split("_")[1:])
    context.user_data["new_artist"]["categoria"] = categoria

    artists = context.bot_data.get("artists", {})
    counter = 1
    while f"artist{counter}" in artists:
        counter += 1
    new_key = f"artist{counter}"

    artists[new_key] = context.user_data["new_artist"]
    context.bot_data["artists"] = artists
    update_artists_file(artists)

    await query.edit_message_text(
        f"_✅ Artista *{escape_markdown(context.user_data['new_artist']['nome'])}* aggiunto con successo nella categoria *{escape_markdown(categoria)}*\\._",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    context.user_data.pop("new_artist", None)
    return MAIN_MENU

async def remove_artist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_artists":
        await query.edit_message_text("Operazione annullata.")
        return MAIN_MENU

    if data.startswith("rm_"):
        key = data[3:]
        artists = context.bot_data.get("artists", {})
        if key in artists:
            artist_to_remove = artists[key]
            nome = artist_to_remove['nome']
            photo_url = artist_to_remove.get('foto')

            if photo_url:
                public_id = get_public_id_from_url(photo_url)
                if public_id:
                    try:
                        cloudinary.uploader.destroy(public_id)
                        logger.info(f"Immagine {public_id} eliminata da Cloudinary.")
                    except Exception as e:
                        logger.error(f"Errore durante l'eliminazione dell'immagine {public_id} da Cloudinary: {e}")

            del artists[key]
            update_artists_file(artists)
            await query.edit_message_text(f"_❎ Artista *{escape_markdown(nome)}* rimosso con successo._", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text("Artista non trovato.")
    return MAIN_MENU

def update_artists_file(artists: dict) -> None:
    content = "artists = " + json.dumps(artists, indent=4, ensure_ascii=False)
    try:
        with open("profili.py", "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Errore nell'aggiornamento di profili.py: {e}")

async def telegram_webhook(request: web.Request) -> web.Response:
    app: Application = request.app["bot_app"]
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return web.Response(status=200)

async def health(request):
    return web.Response(text="OK")

# Modifica la sezione di configurazione del webhook all'inizio del file
WEBHOOK_URL = os.environ["WEBHOOK_URL"].rstrip("/")
WEBHOOK_PATH = f"/{TOKEN}"
FULL_WEBHOOK = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

# Aggiungi debug logging per verificare la configurazione
logger.info(f"TOKEN: {TOKEN[:10]}...")  # Mostra solo i primi 10 caratteri per sicurezza
logger.info(f"WEBHOOK_URL: {WEBHOOK_URL}")
logger.info(f"WEBHOOK_PATH: {WEBHOOK_PATH}")
logger.info(f"FULL_WEBHOOK: {FULL_WEBHOOK}")

async def on_startup(aio_app: web.Application):
    bot_app = Application.builder().token(TOKEN).build()

    # caricare dati bot_data
    data = load_bot_data()
    if data:
        bot_app.bot_data.update(data)
    # esempi di default
    bot_app.bot_data.setdefault("artists", {})  # Corretto da [] a {}
    bot_app.bot_data.setdefault("owners_ids", set())

    # ConversationHandler - correggi il warning
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)],
            VOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, vote_handler)],
            MAIN_MENU: [
                CallbackQueryHandler(owner_button_handler, pattern="^artist[0-9]+$"),
                CallbackQueryHandler(owner_button_handler, pattern="^stop_voting$"),
            ],
            SET_OPTION: [
                CallbackQueryHandler(set_option_callback, pattern="^(set_judges|set_passwords|set_home_picture)$"),
                CallbackQueryHandler(close_keyboard_callback, pattern="^close_keyboard$")
            ],
            SET_DETAIL: [
                CallbackQueryHandler(set_detail_callback, pattern="^(set_limit_popolare|set_limit_tecnica|set_pass_popolare|set_pass_tecnica|set_pass_owner|back_to_main_menu)$")
            ],
            SET_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_value_handler),
                CallbackQueryHandler(back_to_password_menu_callback, pattern="^back_to_password_menu$"),
                CallbackQueryHandler(back_to_limit_menu_callback, pattern="^back_to_limit_menu$")
            ],
            SET_HOME_PICTURE: [
                MessageHandler(filters.PHOTO, set_home_picture_handler)
            ],
            ARTISTI_CHOICE: [
                CallbackQueryHandler(artisti_choice_callback, pattern="^(add_artist|remove_artist|cancel_artists)$")
            ],
            ARTISTI_ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_artist_name_handler)
            ],
            ARTISTI_ADD_AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_artist_age_handler)
            ],
            ARTISTI_ADD_PHOTO: [
                MessageHandler(filters.PHOTO, add_artist_photo_handler)
            ],
            ARTISTI_ADD_SONG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_artist_song_handler)
            ],
            ARTISTI_ADD_CATEGORY: [
                CallbackQueryHandler(add_artist_category_handler, pattern="^categoria_")
            ],
            ARTISTI_REMOVE: [
                CallbackQueryHandler(remove_artist_callback, pattern="^(rm_.*|cancel_artists)$")
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,  # Cambiato da True a False per evitare il warning
        per_user=True,
        per_chat=True,
    )

    # registra handler - correggi il comando 'set'
    bot_app.add_handler(CommandHandler('set', set_limit_command))  # Corretto
    bot_app.add_handler(CommandHandler('artisti', artisti_command))
    bot_app.add_handler(CommandHandler('votazioni', votazioni_command))
    bot_app.add_handler(CommandHandler('reset', reset_voting))
    bot_app.add_handler(CommandHandler('logout', logout))
    bot_app.add_handler(CommandHandler('cancel', cancel))
    bot_app.add_handler(conv, group=1)
    bot_app.add_handler(CallbackQueryHandler(owner_button_handler))

    await bot_app.initialize()
    await bot_app.start()

    # Imposta il webhook con logging dettagliato
    try:
        webhook_info = await bot_app.bot.get_webhook_info()
        logger.info(f"Webhook info attuale: {webhook_info}")
        
        result = await bot_app.bot.set_webhook(FULL_WEBHOOK)
        logger.info(f"Risultato set_webhook: {result}")
        
        # Verifica che il webhook sia stato impostato correttamente
        new_webhook_info = await bot_app.bot.get_webhook_info()
        logger.info(f"Nuovo webhook info: {new_webhook_info}")
        
    except Exception as e:
        logger.error(f"Errore nell'impostazione del webhook: {e}")

    aio_app["bot_app"] = bot_app
    logger.info("Webhook impostato su: %s", FULL_WEBHOOK)

async def on_cleanup(aio_app: web.Application):
    bot_app: Application = aio_app["bot_app"]
    await bot_app.stop()
    await bot_app.shutdown()


def main():
    # Verifica che TOKEN sia impostato
    if not TOKEN:
        logger.error("TOKEN non impostato nelle variabili d'ambiente!")
        return
    
    # Verifica che WEBHOOK_URL sia impostato
    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        logger.error("WEBHOOK_URL non impostato nelle variabili d'ambiente!")
        return
    
    logger.info(f"Avvio bot con TOKEN: {TOKEN[:10]}...")
    logger.info(f"WEBHOOK_URL: {webhook_url}")
    logger.info(f"WEBHOOK_PATH: {WEBHOOK_PATH}")
    logger.info(f"FULL_WEBHOOK: {FULL_WEBHOOK}")
    
    aio_app = web.Application()
    aio_app.on_startup.append(on_startup)
    aio_app.on_cleanup.append(on_cleanup)

    # health-check (opzionale ma utile)
    aio_app.router.add_get("/", health)

    # monta l'unico POST che serve, su /<TOKEN>
    aio_app.router.add_post(WEBHOOK_PATH, telegram_webhook)
    logger.info(f"Route POST configurata su: {WEBHOOK_PATH}")

    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Avvio server su porta: {port}")
    web.run_app(aio_app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
