// Link previews: chat apps and social sites fetch a link with a bot that doesn't run JavaScript, so they'd only ever see the
// generic page title. For those bots, hand back a tiny page with that address's title, description and preview picture
// (built into /og by og.py). Everyone else gets the real site untouched.
export const config = { matcher: ['/((?!og/|favicon|robots|.*\\.(?:jpg|png|ico|txt|xml|js|css|woff2)$).*)'] };

const BOT = /facebookexternalhit|Facebot|Twitterbot|Slackbot|Discordbot|WhatsApp|TelegramBot|LinkedInBot|Applebot|Googlebot|bingbot|Embedly|redditbot|SkypeUriPreview|Pinterest|vkShare|iframely|Snapchat|Iframely/i;
const PAGES = new Set(['standings', 'schedule', 'playoffs', 'records', 'teams', 'players', 'news', 'races', 'trades', 'transactions', 'draft', 'h2h', 'excitement', 'analyzer']);

function keyFor(path) {
  const p = decodeURIComponent(path).replace(/\/+$/, '').toLowerCase();
  if (!p) return 'home';
  let m;
  if ((m = /^\/week(\d+)\/([^\/]+)/.exec(p))) return `game-${m[1]}-${m[2]}`;
  if ((m = /^\/week(\d+)$/.exec(p))) return `week-${m[1]}`;
  if ((m = /^\/news\/([^\/]+)/.exec(p))) return `news-${m[1]}`;
  if ((m = /^\/player\/([^\/]+)/.exec(p))) return `player-${m[1]}`;
  if ((m = /^\/game\/w(\d+)-(\d+)-(\d+)/.exec(p))) return `g-${m[1]}-${m[2]}-${m[3]}`;
  const seg = p.split('/')[1] === 'team' ? p.split('/')[2] : p.split('/')[1];
  if (PAGES.has(seg)) return `page-${seg}`;
  return `team-${seg}`;
}

export default async function middleware(req) {
  if (!BOT.test(req.headers.get('user-agent') || '')) return;          // people: carry on to the site
  const url = new URL(req.url);
  for (const k of [keyFor(url.pathname), 'home']) {
    const r = await fetch(new URL(`/og/${k}.html`, url));
    if (r.ok) return new Response(await r.text(), { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'public, max-age=300' } });
  }
}
