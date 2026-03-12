const QUICK_TO = [
  "Phuket",
  "Chiang Mai",
  "Krabi",
  "Pattaya",
  "Hua Hin",
  "Koh Samui",
  "Surat Thani",
  "Ayutthaya",
  // Special option: triggers free-text entry (handled in main.js)
  "__OTHER__",
];
const QUICK_FROM = ["Bangkok","Chiang Mai","Phuket","Pattaya","Krabi","Hua Hin","Surat Thani","Koh Samui"];

export function renderQuickTo({ ui, onPick, title }) {
  ui.addButtonsBubble({
    title: title || "Where are you going?",
    options: QUICK_TO.map(x => ({ value: x, label: x === "__OTHER__" ? "Other…" : x })),
    onPick: async (opt) => onPick(opt.value),
  });
}

export function renderQuickFrom({ ui, onPick, title }) {
  ui.addButtonsBubble({
    title: title || "Where are you departing from?",
    options: QUICK_FROM.map(x => ({ value: x, label: x })),
    onPick: async (opt) => onPick(opt.value),
  });
}
