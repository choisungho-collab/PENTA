// 배포(Netlify 빌드) 시 실행 — 전체 챔피언의 스킨 번호만 추려 web/skins.json 을 만든다.
//  - DataDragon championFull.json(전체 챔피언+스킨)에서 num 만 뽑아 경량화(수십 KB).
//  - 결과: { version, champions: { Ahri:[0,1,2,...], Lux:[...], ... } }
//  - 실패해도 배포는 계속되도록 exit 0 (웹은 skins.json 없으면 개별 로드로 폴백).
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';

async function main() {
  const vRes = await fetch('https://ddragon.leagueoflegends.com/api/versions.json');
  const versions = await vRes.json();
  const ver = (Array.isArray(versions) && versions[0]) || '15.1.1';

  const fRes = await fetch('https://ddragon.leagueoflegends.com/cdn/' + ver + '/data/en_US/championFull.json');
  const full = await fRes.json();
  const data = (full && full.data) || {};

  const champions = {};
  for (const key in data) {
    const skins = (data[key] && data[key].skins) || [];
    // 크로마는 원화(splash)가 없다 → parentSkin 필드가 있는 항목(=크로마) 제외, base 스킨만.
    const nums = skins
      .filter((s) => s && s.parentSkin == null)
      .map((s) => s.num)
      .filter((n) => typeof n === 'number');
    if (nums.length) champions[key] = nums;
  }

  const count = Object.keys(champions).length;
  if (!count) throw new Error('no champions parsed');

  if (!existsSync('web')) mkdirSync('web', { recursive: true });
  writeFileSync('web/skins.json', JSON.stringify({ version: ver, champions }));
  console.log('skins.json generated: ' + count + ' champions (patch ' + ver + ')');
}

main().catch((e) => {
  console.error('gen-skins skipped: ' + (e && e.message));
  process.exit(0); // 배포는 계속 (웹이 폴백)
});
