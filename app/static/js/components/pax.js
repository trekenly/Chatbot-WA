export function renderPaxAsk({ ui, onPick, title }) {
  let n = 1;

  // A compact stepper using buttons bubble.
  ui.addButtonsBubble({
    title: title || "How many tickets?",
    options: [
      { value: "1", label: "1" },
      { value: "2", label: "2" },
      { value: "3", label: "3" },
      { value: "4", label: "4" },
      { value: "5", label: "5" },
      { value: "6", label: "6" },
      { value: "7", label: "7" },
      { value: "8", label: "8" },
    ],
    onPick: async (opt) => {
      n = Math.max(1, Math.min(20, parseInt(opt.value, 10) || 1));
      await onPick(String(n));
    },
  });
}
