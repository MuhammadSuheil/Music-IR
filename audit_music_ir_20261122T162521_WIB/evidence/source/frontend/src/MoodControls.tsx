import type { MoodBasis, SearchResult } from './lib'

export default function MoodControls({ mood, onChange }: {
  mood: NonNullable<SearchResult['mood']>; onChange: (basis: MoodBasis) => void
}) {
  return <section className="mood-controls" aria-label="Dasar pencarian suasana">
    <div><strong>{mood.label === 'sad' ? 'Sedih dari lirik, musik, atau keduanya?' : 'Ceria dari lirik, musik, atau keduanya?'}</strong>
      <p>Makna lirik dan nuansa musik bisa berbeda. Pilih yang ingin kamu dengarkan.</p></div>
    <div className="mood-basis-buttons" role="group" aria-label="Pilihan dasar suasana">
      {([['both', 'Makna + musik'], ['lyrics', 'Makna lirik'], ['audio', 'Nuansa musik']] as const).map(([basis, label]) =>
        <button key={basis} aria-pressed={mood.basis === basis} className={mood.basis === basis ? 'selected' : ''} onClick={() => onChange(basis)}>{label}</button>)}
    </div>
    <p className="mood-scope-note">{mood.basis === 'lyrics' ? 'Mengurutkan berdasarkan makna teks. Musiknya tetap bisa terdengar ceria atau berenergi.' :
      mood.basis === 'audio' ? 'Memakai perkiraan nuansa dari data audio; makna lirik tidak dinilai dalam pilihan ini.' :
        'Menggabungkan makna teks dengan penyaringan perkiraan nuansa dari data audio.'}</p>
    {mood.audio_constraints.length > 0 && <details><summary>Dasar penyaringan musik</summary><p>{mood.audio_constraints.map(([field, operator, value]) => `${field} ${operator} ${value}`).join(' · ')}</p><p>{mood.note}</p></details>}
  </section>
}
