// Local-only reviewer form. Every answer starts unreviewed; identities stay blank.
const bindings = JSON.parse(document.getElementById("bindings").textContent);
for (const card of document.querySelectorAll("article[data-result]")) {
  const controls = document.createElement("div");
  for (const [name, values] of Object.entries({
    relevance: [
      "unreviewed",
      "clearly_related",
      "partially_related",
      "unrelated",
    ],
    duplicate_status: ["unreviewed", "unique", "duplicate"],
    media_valid: ["unreviewed", "yes", "no"],
    low_quality: ["unreviewed", "yes", "no"],
  })) {
    const label = document.createElement("label");
    label.append(name + " ");
    const select = document.createElement("select");
    select.name = name;
    for (const value of values) select.add(new Option(value, value));
    label.append(select);
    controls.append(label, document.createElement("br"));
  }
  for (const name of ["duplicate_group", "notes"]) {
    const label = document.createElement("label");
    label.append(name + " ");
    const input = document.createElement("input");
    input.name = name;
    label.append(input);
    controls.append(label, document.createElement("br"));
  }
  card.append(controls);
}
const quote = (value) => '"' + String(value ?? "").replaceAll('"', '""') + '"';
document.getElementById("export-labels").onclick = () => {
  const reviewer = document.getElementById("reviewer").value.trim();
  if (!reviewer) {
    document.getElementById("review-message").textContent =
      "Enter your actual reviewer identity.";
    return;
  }
  const rows = [];
  for (const card of document.querySelectorAll("article[data-result]")) {
    const row = { ...bindings[Number(card.dataset.result)] };
    for (const input of card.querySelectorAll("input,select"))
      row[input.name] = input.value;
    row.reviewer = reviewer;
    rows.push(row);
  }
  if (!rows.length) {
    document.getElementById("review-message").textContent =
      "No candidate files exist; no human labels can be exported.";
    return;
  }
  const columns = [
    "case_id",
    "job_id",
    "revision",
    "candidate_id",
    "rank",
    "sha256",
    "relevance",
    "duplicate_group",
    "duplicate_status",
    "media_valid",
    "low_quality",
    "notes",
    "reviewer",
  ];
  const csv =
    [
      columns.map(quote).join(","),
      ...rows.map((row) => columns.map((key) => quote(row[key])).join(",")),
    ].join("\r\n") + "\r\n";
  const url = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "labels.csv";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
