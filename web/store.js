let database;

function open() {
  if (!database)
    database = new Promise((resolve, reject) => {
      const request = indexedDB.open("memeretrieve-web", 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore("session");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () =>
        reject(new Error("Browser storage is blocked by another tab."));
    });
  return database;
}

async function transaction(write, value) {
  try {
    const db = await open();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("session", write ? "readwrite" : "readonly");
      const store = tx.objectStore("session");
      const request = write
        ? value === null
          ? store.delete("current")
          : store.put(value, "current")
        : store.get("current");
      tx.oncomplete = () => resolve(write ? undefined : request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } catch {
    throw new Error(
      "Cannot save this search locally. Check browser storage space and permissions, then retry.",
    );
  }
}

export const loadSession = () => transaction(false);
export const saveSession = (value) => transaction(true, value);
