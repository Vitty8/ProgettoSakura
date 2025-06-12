from telegram import Update
from telegram.helpers import escape_markdown 

def get_benvenuto_popolare_text(update: Update) -> str:
    user = update.effective_user
    escaped_first_name = escape_markdown(user.first_name, version=2)
    nickname_clickable = f"[{escaped_first_name}](tg://user?id={user.id})"
    text = (
        f"_*Benvenuto nel portale della Giuria Popolare, {nickname_clickable}\\!*_\n\n"
        "_Qui avrai la possibilità di esprimere le tue preferenze sugli artisti con un voto che va da 1 a 10\\._\n\n"
        "_Attendi che ti venga mostrato il profilo dell'artista per esprimere il tuo voto\\._"
    )
    return text

def get_benvenuto_tecnica_text(update: Update) -> str:
    user = update.effective_user
    escaped_first_name = escape_markdown(user.first_name, version=2)
    nickname_clickable = f"[{escaped_first_name}](tg://user?id={user.id})"
    text = (
        f"_*Benvenuto nel portale della Giuria Tecnica, {nickname_clickable}\\!*_\n\n"
        "Siamo entusiasti di averti qui con noi\\. La tua voce conta e il tuo contributo è fondamentale "
        "per rendere giusta ogni decisione\\. Grazie per esserti unito a questa importante iniziativa\\!\n\n"
        "_Attendi che ti venga mostrato il profilo dell'artista per esprimere il tuo voto per ogni ambito\\._"
    )
    return text

def get_benvenuto_prop_text(update: Update) -> str:
    user = update.effective_user
    escaped_first_name = escape_markdown(user.first_name, version=2)
    nickname_clickable = f"[{escaped_first_name}](tg://user?id={user.id})"
    text = (
        f"_*Benvenuto {nickname_clickable}\\!*_\n\n"
        "Da qui potrai gestire tutto ciò che riguarda le votazioni del Festival, ti spiego in breve i vari comandi a tua disposizione\\:\n\n"
        "_\\- /set, questo comando ti permette di impostare il numero massimo di giudici che possono effettuare l'accesso\\._\n"
        "_Inoltre potrai cambiare, a tuo piacimento, le password per effettuare il login\\._\n"
        "_\\- /artisti, da qui avrai la possibilità di aggiungere o rimuovere gli artisti che verranno poi votati dalla giuria\\._\n"
        "_\\- /votazioni, quando tutto sarà pronto usa questo comando per far comparire la tastiera con tutti gli artisti, premendo su un nome_ " 
        "_darai inizio alle votazioni per quel singolo artista\\._\n\n"
        "*Spero sia tutto chiaro, detto ciò, in bocca al lupo e buon festival\\!*"
    )
    return text

def welcome_text(update: Update) -> str:
    text = (
        "*Benvenuto al Sakura Festival\\! 🎤*\n\n"
        "_Se fai parte della giuria digita la password che ti è stata fornita per entrare nell'apposito portale e dare il tuo contributo\\._\n"
    )    
    return text