// 郵便番号（7桁）を入力すると、zipcloud（日本郵便のデータを使った無料API）で
// 都道府県名・市区郡名・町村名を自動入力する。手入力済みの欄は上書きしない。
document.addEventListener("DOMContentLoaded", () => {
  const postal = document.getElementById("postal_code");
  if (!postal) return;
  const prefecture = document.getElementById("prefecture");
  const city = document.getElementById("city");
  const town = document.getElementById("town");

  let lastLookedUp = "";

  async function fillAddress() {
    const digits = postal.value.replace(/[^0-9]/g, "");
    if (digits.length !== 7 || digits === lastLookedUp) return;
    lastLookedUp = digits;
    try {
      const res = await fetch(`https://zipcloud.ibsnet.co.jp/api/search?zipcode=${digits}`);
      const data = await res.json();
      const r = data.results && data.results[0];
      if (!r) return;
      if (prefecture && !prefecture.value) prefecture.value = r.address1;
      if (city && !city.value) city.value = r.address2;
      if (town && !town.value) town.value = r.address3;
    } catch (e) {
      // 通信エラー時は何もしない（手入力の邪魔をしない）
    }
  }

  postal.addEventListener("blur", fillAddress);
  postal.addEventListener("input", fillAddress);
});
