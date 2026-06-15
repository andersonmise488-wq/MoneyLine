/** Dutching stakes for equal return across arb legs. */

const SPORT_EMOJI = {
  soccer: "⚽",
  tennis: "🎾",
  basketball: "🏀",
  volleyball: "🏐",
  handball: "🤾",
  baseball: "⚾",
  cricket: "🏏",
  ice_hockey: "🏒",
};

const SPORT_ORDER = [
  "soccer",
  "tennis",
  "basketball",
  "volleyball",
  "handball",
  "baseball",
  "cricket",
  "ice_hockey",
];

function fmtSportLabel(sport) {
  if (!sport) return "—";
  const key = String(sport).toLowerCase();
  const emoji = SPORT_EMOJI[key] || "🎯";
  const label = key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return `${emoji} ${label}`;
}

function fmtBySportCounts(bySport) {
  if (!bySport || typeof bySport !== "object") return "—";
  return SPORT_ORDER.map((key) => {
    const n = bySport[key] ?? 0;
    const emoji = SPORT_EMOJI[key] || "🎯";
    return `${emoji}${n}`;
  }).join(" · ");
}

const HANDICAP_MARKETS = new Set([

  "asian_handicap",

  "european_handicap",

  "game_handicap",

  "spread",

  "set_handicap",

  "run_line",

  "puck_line",

]);



function fmtLineValue(line) {

  const n = Number(line);

  if (Number.isInteger(n)) return String(n);

  return String(n);

}



function fmtSignedHandicap(value) {

  const text = fmtLineValue(value);

  return value > 0 ? `+${text}` : text;

}



function handicapLineForSide(side, line) {

  if (line == null) return null;

  const n = Number(line);

  if (side === "home") return n;

  if (side === "away") return -n;

  return null;

}



function fmtBetPick(opp, leg) {

  const side = (leg.side || "").toLowerCase();

  const price = Number(leg.price).toFixed(2);

  const line = leg.line != null ? leg.line : opp?.line;

  const marketKey = opp?.market_key || "";

  const priceText = `@ ${price}`;



  if (HANDICAP_MARKETS.has(marketKey) && (side === "home" || side === "away")) {

    const signed = handicapLineForSide(side, line);

    if (signed != null) {

      const team = side === "home" ? opp.home_team : opp.away_team;

      return `${team} (${fmtSignedHandicap(signed)}) ${priceText}`;

    }

  }



  if (side === "over" && line != null) return `Over ${fmtLineValue(line)} ${priceText}`;

  if (side === "under" && line != null) return `Under ${fmtLineValue(line)} ${priceText}`;

  if (marketKey === "btts" && side === "yes") return `BTTS Yes ${priceText}`;

  if (marketKey === "btts" && side === "no") return `BTTS No ${priceText}`;

  if (side === "yes") return `Yes ${priceText}`;

  if (side === "no") return `No ${priceText}`;

  if (side === "home" && opp?.home_team) return `${opp.home_team} ${priceText}`;

  if (side === "away" && opp?.away_team) return `${opp.away_team} ${priceText}`;

  if (side === "draw") return `Draw ${priceText}`;



  return `${leg.label || side} ${priceText}`;

}



function optimalStakes(legs, bankroll) {

  if (!legs?.length || !bankroll || bankroll <= 0) return legs || [];

  const implied = legs.map((l) => 1 / Number(l.price));

  const total = implied.reduce((a, b) => a + b, 0);

  if (total <= 0) return legs;

  return legs.map((leg, i) => {

    const stake = (bankroll * implied[i]) / total;

    const price = Number(leg.price);

    return {

      ...leg,

      stake: Math.round(stake * 100) / 100,

      return: Math.round(stake * price * 100) / 100,

    };

  });

}



function fmtKes(n) {

  return `KES ${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

}



function fmtLegsWithStakes(legs, bankroll, opp) {

  const staked = optimalStakes(legs, bankroll);

  return staked

    .map((l) => {

      const pick = opp ? fmtBetPick(opp, l) : `${l.label || l.side} @ ${Number(l.price).toFixed(2)}`;

      const bookmaker = l.bookmaker || "";

      const stakeText = bankroll > 0 ? ` · Stake ${fmtKes(l.stake)} · Return ${fmtKes(l.return)}` : "";

      const betLink = l.place_bet_url

        ? ` · <a class="place-bet" href="${l.place_bet_url}" target="_blank" rel="noopener">Place Bet</a>`

        : "";

      return `${bookmaker} · ${pick}${stakeText}${betLink}`;

    })

    .join("<br>");

}



function calcProfit(legs, bankroll) {

  const staked = optimalStakes(legs, bankroll);

  if (!staked.length || !bankroll) return null;

  const totalStake = staked.reduce((s, l) => s + (l.stake || 0), 0);

  const ret = Math.min(...staked.map((l) => l.return || 0));

  return { totalStake, guaranteedReturn: ret, profit: ret - totalStake };

}

