from __future__ import annotations

import random
import logging

import discord
from discord.ext import commands


log = logging.getLogger("maggika.risposta_ping")

PING_GIF_CHANCE = 0.35


PING_REPLIES = [
    "Io non porto sfortuna, porto realismo. È diverso, fa solo più male.",
    "CastaMaggic dice che andrà tutto bene. Io dico: dipende da quanto sei disposto a mentire a te stesso.",
    "Non sono cattiva, ho solo finito la pazienza nel 2019.",
    "Se la vita ti sorride, controlla che non ti stia prendendo in giro.",
    "Io credo nelle seconde possibilità. Soprattutto quando la prima mi fa ridere abbastanza.",
    "Il mio superpotere è capire subito chi mi farà perdere tempo.",
    "Casta fa magia. Io faccio sparire l’autostima alle persone, ma con eleganza.",
    "Non sono pessimista, sono una persona ottimista con accesso alle statistiche.",
    "Se vuoi una risposta sincera, chiedimela. Se vuoi stare bene, evita.",
    "Mi hanno detto di seguire i miei sogni. Peccato che anche loro mi abbiano bloccata.",
    "Il problema non è che sei strano. È che sei strano senza contenuto.",
    "Io non giudico nessuno. Archivio informazioni per usarle al momento giusto.",
    "La tua energia è bellissima. Nel senso che si spegne subito.",
    "Non ho standard alti. Ho solo visto abbastanza disastri umani.",
    "CastaMaggic evoca contenuti. Io evoco traumi con una frase.",
    "Vorrei essere più dolce, ma poi la gente inizierebbe a parlarmi.",
    "La vita è breve. Ma alcune conversazioni riescono comunque a sembrare eterne.",
    "Non ti odio. Ti considero un esercizio di autocontrollo.",
    "Sono una persona solare, solo che il mio sole è in modalità eclissi.",
    "Sei unico. E a volte questa non è una buona notizia.",
    "Il karma esiste, ma secondo me è in ferie.",
    "Non sono fredda. Sono in risparmio energetico emotivo.",
    "La mia red flag? Vedo le tue e resto comunque per curiosità scientifica.",
    "Io non creo drama. Gli do solo una sedia e lo lascio parlare.",
    "CastaMaggic fa video per intrattenere. Io entro in stanza e la gente rivaluta le proprie scelte.",
    "Mi piace aiutare gli altri. A capire che avevo ragione.",
    "Non sono difficile da conquistare. Sono facile da deludere.",
    "La speranza è l’ultima a morire, ma io le ho già prenotato il funerale.",
    "Ho un cuore grande. Solo che è protetto da sarcasmo, diffidenza e password a due fattori.",
    "Non sono tossica, sono un’esperienza formativa.",
    "Sei pieno di potenziale. Che, tradotto, significa che per ora non hai combinato nulla.",
    "Il mio umorismo è nero perché quello rosa era già finito.",
    "Amo le persone sincere. Da lontano. In silenzio. Senza notifiche.",
    "Non ti sto ignorando. Sto dando valore alla mia pace mentale.",
    "CastaMaggic crea magia. Io creo silenzi imbarazzanti e li chiamo atmosfera.",
]

PING_GIFS = [
    "https://media.giphy.com/media/3o7abldj0b3rxrZUxW/giphy.gif",
    "https://media.giphy.com/media/13HgwGsXF0aiGY/giphy.gif",
    "https://media.giphy.com/media/xT9IgG50Fb7Mi0prBC/giphy.gif",
    "https://media.giphy.com/media/26gsjCZpPolPr3sBy/giphy.gif",
    "https://media.giphy.com/media/l0HlBO7eyXzSZkJri/giphy.gif",
    "https://media.giphy.com/media/ule4vhcY1xEKQ/giphy.gif",
    "https://media.giphy.com/media/FspLvJQlQACXu/giphy.gif",
    "https://media.giphy.com/media/kaq6GnxDlJaBq/giphy.gif",
    "https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif",
    "https://media.giphy.com/media/8vQSQ3cNXuDGo/giphy.gif",
    "https://media.giphy.com/media/3o7TKtnuHOHHUjR38Y/giphy.gif",
    "https://media.giphy.com/media/l4FGuhL4U2WyjdkaY/giphy.gif",
    "https://media.giphy.com/media/6nWhy3ulBL7GSCvKw6/giphy.gif",
    "https://media.giphy.com/media/JSueytO5O29yM/giphy.gif",
    "https://media.giphy.com/media/ji6zzUZwNIuLS/giphy.gif",
    "https://media.giphy.com/media/5VKbvrjxpVJCM/giphy.gif",
    "https://media.giphy.com/media/ANbD1CCdA3iI8/giphy.gif",
    "https://media.giphy.com/media/WRQBXSCnEFJIuxktnw/giphy.gif",
]


class RispostaPing(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if self.bot.user is None:
            return

        if message.mention_everyone or not self.bot.user.mentioned_in(message):
            return

        content = random.choice(PING_REPLIES)
        if random.random() < PING_GIF_CHANCE:
            content = f"{content}\n{random.choice(PING_GIFS)}"

        await message.reply(
            content=content,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    log.info(
        "RispostaPing caricato con %s frasi e %s gif. Chance gif: %.0f%%.",
        len(PING_REPLIES),
        len(PING_GIFS),
        PING_GIF_CHANCE * 100,
    )
    await bot.add_cog(RispostaPing(bot))
