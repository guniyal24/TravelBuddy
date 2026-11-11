// Static content for the marketing page and the planner's quick picks.
// Only towns the planner can actually plan are listed as plannable.

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];

export const TIERS = { budget: "Budget", mid: "Mid-range", premium: "Premium" };

// Town photos: Wikimedia Commons, resized to 800px wide (and the Ranikhet panorama cropped).
// Each licence needs the author and licence shown: see PhotoCredits.
export const PHOTOS = {
  haridwar: { src: "towns/haridwar.jpg", alt: "Evening Ganga aarti at Har Ki Pauri, Haridwar", author: "pavankunar", license: "CC BY-SA 4.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0", source: "https://commons.wikimedia.org/wiki/File:Ganga_aarti_haridwar_01.jpg" },
  rishikesh: { src: "towns/rishikesh.jpg", alt: "Lakshman Jhula bridge over the Ganga, Rishikesh", author: "Snehrashmi", license: "CC BY-SA 4.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0", source: "https://commons.wikimedia.org/wiki/File:Lakshman_Jhula_Bridge_-_Hrishikesh_-_Uttarakhand_001.jpg" },
  dehradun: { src: "towns/dehradun.jpg", alt: "Forest Research Institute, Dehradun", author: "DesiBoy101", license: "CC BY 4.0", licenseUrl: "https://creativecommons.org/licenses/by/4.0", source: "https://commons.wikimedia.org/wiki/File:Forest_Research_Institute_in_Dehradun_54.jpg" },
  mussoorie: { src: "towns/mussoorie.jpg", alt: "Snow on the ridge at Mussoorie above the Doon valley", author: "Paul Hamilton", license: "CC BY-SA 2.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/2.0", source: "https://commons.wikimedia.org/wiki/File:Mussoorie_Snow_Over_Dehradun_(14831297545).jpg" },
  nainital: { src: "towns/nainital.jpg", alt: "Naini Lake and the town of Nainital from above", author: "Skalvanov", license: "CC BY-SA 4.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0", source: "https://commons.wikimedia.org/wiki/File:Nainital_metro.jpg" },
  almora: { src: "towns/almora.jpg", alt: "Almora town on its ridge", author: "Travelling Slacker", license: "CC BY 2.0", licenseUrl: "https://creativecommons.org/licenses/by/2.0", source: "https://commons.wikimedia.org/wiki/File:Almora_Uttarakhand_India_2013.jpg" },
  ranikhet: { src: "towns/ranikhet.jpg", alt: "Himalayan peaks seen from Ranikhet", author: "Harshit SR (panorama by Unpetitpro)", license: "CC BY-SA 4.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0", source: "https://commons.wikimedia.org/wiki/File:Panorama_of_Himalayas_from_Ranikhet,_Uttarakhand,_India.jpg" },
  jim_corbett: { src: "towns/jim_corbett.jpg", alt: "A Bengal tiger in Jim Corbett National Park", author: "Soumyajit Nandy", license: "CC BY-SA 3.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/3.0", source: "https://commons.wikimedia.org/wiki/File:Bengal-Tiger_Corbett_Uttarakhand_Dec-2013.jpg" },
  badrinath: { src: "towns/badrinath.jpg", alt: "Badrinath Temple", author: "Anubha khare", license: "CC BY-SA 4.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0", source: "https://commons.wikimedia.org/wiki/File:Badrinath_Temple_,_Uttarakhand.jpg" },
};

export const DESTINATIONS = [
  { id: "haridwar", name: "Haridwar", tagline: "Ganga aarti, ghats and old temples", tags: ["Spiritual", "Food"], g: ["#043e56", "#2f87b5"] },
  { id: "rishikesh", name: "Rishikesh", tagline: "Yoga, rafting and riverside cafes", tags: ["Adventure", "Yoga"], g: ["#0a6a8f", "#52b6d9"] },
  { id: "dehradun", name: "Dehradun", tagline: "The easy gateway to the hills", tags: ["City", "Gateway"], g: ["#0f766e", "#3dbfae"] },
  { id: "mussoorie", name: "Mussoorie", tagline: "Queen of the hills, Mall Road and misty views", tags: ["Hill station", "Views"], g: ["#c2410c", "#f59a3c"] },
  { id: "nainital", name: "Nainital", tagline: "A lake town in the Kumaon hills", tags: ["Lakes", "Family"], g: ["#1d4f91", "#5d9be0"] },
  { id: "almora", name: "Almora", tagline: "Kumaoni culture and Himalayan views", tags: ["Culture", "Quiet"], g: ["#7a3412", "#e9782a"] },
  { id: "ranikhet", name: "Ranikhet", tagline: "Pine forests and a slow pace", tags: ["Nature", "Quiet"], g: ["#0b5563", "#35a9b8"] },
  { id: "jim_corbett", name: "Jim Corbett", tagline: "Jungle country and the national park", tags: ["Wildlife", "Safari"], g: ["#9a3412", "#f0883a"] },
  { id: "badrinath", name: "Badrinath", tagline: "A Char Dham shrine high in the Himalaya", tags: ["Pilgrimage", "High altitude"], g: ["#04506f", "#e94d04"] },
];

export const STEPS_INFO = [
  { icon: "pen", title: "Describe", text: "Tell it your days, group, month, budget and interests, in English, Hindi or Hinglish." },
  { icon: "route", title: "Choose", text: "Pick from circuits that suit your month. Risky seasons are flagged before you commit." },
  { icon: "check", title: "Review", text: "Get a validated day-by-day plan with a cost range. Ask for changes until it feels right." },
  { icon: "ticket", title: "Book", text: "Approve it and get a booking checklist with links to the official sites. You pay there." },
];

export const FEATURES = [
  { icon: "book", title: "Grounded in real listings", text: "Plans and answers use places from a curated knowledge base, with sources. If it does not know, it says so instead of guessing." },
  { icon: "shield", title: "A safety agent on every plan", text: "Checks altitude jumps, high-altitude health risks, Char Dham registration and monthly road and weather advisories." },
  { icon: "wallet", title: "Honest cost ranges", text: "Totals are ranges, and every line says whether it comes from a listing or from an assumption." },
  { icon: "refresh", title: "Re-plan when things change", text: "Rain, a cancelled bus, a change of mind: re-plan from any day and the earlier days stay exactly as they were." },
  { icon: "language", title: "English, Hindi and Hinglish", text: "Talk to it your way. Plans and chat answers follow your language." },
  { icon: "map", title: "Map, timeline and offline copies", text: "A day-by-day timeline, a map of your stops, a booking checklist, and saved trips that open without a connection." },
];

export const STACK = ["LangGraph", "Self-RAG", "MCP tools", "Neo4j", "Pinecone", "FastAPI", "React"];

export const FAQ = [
  ["Does it book anything for me?", "No. It gives you a checklist with links to the official booking sites. You pay there, and tick items off here to track your progress."],
  ["How reliable are the costs and travel times?", "Costs are ranges. Each line is marked as coming from a listing or from an assumption. Road distances and hours are estimates, so check live conditions before you travel."],
  ["Which places can it plan?", "26 towns across Garhwal and Kumaon: the classics (Haridwar, Rishikesh, Mussoorie, Nainital, Almora, Jim Corbett) plus Kedarnath, Badrinath, Gangotri, Auli, the Valley of Flowers, Chopta, Kausani, Mukteshwar, Bhimtal, Lansdowne, Munsiyari, Pithoragarh and more. Places come from Wikivoyage and OpenStreetMap."],
  ["Can I use it offline?", "The app opens offline and your recently opened trips stay available. Planning and chat need a connection, and map tiles need one too."],
  ["Is my data private?", "Your account, preferences and trips are stored for your login only. It is a portfolio project, so please do not enter anything sensitive."],
];
