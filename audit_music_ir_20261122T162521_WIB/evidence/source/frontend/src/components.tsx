import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Check, Clock3, Heart, MoreHorizontal, Music2, Play, Plus, X } from 'lucide-react'
import type { Track } from './lib'
import { duration } from './lib'
import artwork from './artwork.json'

export function Artwork({ track, className = '', artist = false }: { track: Track; className?: string; artist?: boolean }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [track.album_id])
  const item = (artwork as Record<string, { path: string }>)[track.album_id]
  const hue = [...track.title].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 360
  return <div className={`artwork ${artist ? 'artist-art' : ''} ${className}`}
    style={{ '--art-hue': hue } as CSSProperties}>
    {item && !failed ? <img src={item.path} alt={`Sampul ${track.album || track.title}`} loading="lazy" onError={() => setFailed(true)} /> :
      <div className="artwork-fallback"><Music2 size={38} strokeWidth={1.3} /><span>{track.title}</span></div>}
  </div>
}

export function IconButton({ label, children, active = false, className = '', ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode; active?: boolean }) {
  return <button {...props} type="button" className={`icon-button ${active ? 'is-active' : ''} ${className}`}
    aria-label={label} title={label}>{children}</button>
}

export function TrackCard({ track, onSelect, onPlay, artist = false, onArtist }: {
  track: Track; onSelect: (track: Track) => void; onPlay: (track: Track) => void; artist?: boolean; onArtist?: () => void
}) {
  return <article className={`track-card ${artist ? 'artist-card' : ''}`}>
    <div className="card-art-wrap">
      <button className="art-button" onClick={() => artist ? onArtist?.() : onSelect(track)}
        aria-label={artist ? `Cari ${track.artist}` : `Detail ${track.title}`}><Artwork track={track} artist={artist} /></button>
      <button className="green-play card-play" onClick={() => onPlay(track)} aria-label={`Dengarkan ${track.title}`}><Play size={22} fill="currentColor" /></button>
    </div>
    <button className="card-title" onClick={() => artist ? onArtist?.() : onSelect(track)}>{artist ? track.artist.split(',')[0] : track.title}</button>
    <p>{artist ? 'Artis' : track.artist}</p>
  </article>
}

export function TrackTable({ tracks, selectedId, liked, onSelect, onPlay, onLike, onAdd }: {
  tracks: Track[]; selectedId?: string; liked: Set<string>; onSelect: (track: Track) => void
  onPlay: (track: Track) => void; onLike: (track: Track) => void; onAdd: (track: Track) => void
}) {
  return <div className="table-scroll"><table className="track-table">
    <thead><tr><th className="number-cell">#</th><th>Judul</th><th className="album-cell">Album</th><th className="year-cell">Tahun</th><th className="save-cell"><span className="sr-only">Simpan</span></th><th className="duration-cell"><Clock3 size={17} aria-label="Durasi" /></th><th className="menu-cell"><span className="sr-only">Opsi</span></th></tr></thead>
    <tbody>{tracks.map((track, index) => <tr key={track.track_id} className={track.track_id === selectedId ? 'selected-row' : ''} onDoubleClick={() => onPlay(track)}>
      <td className="number-cell"><span className="row-number">{index + 1}</span><button className="row-play" aria-label={`Dengarkan ${track.title}`} onClick={() => onPlay(track)}><Play size={16} fill="currentColor" /></button></td>
      <td><div className="table-track"><button className="art-button" onClick={() => onSelect(track)} aria-label={`Detail ${track.title}`}><Artwork track={track} /></button><div><button className="track-title" onClick={() => onSelect(track)}>{track.title}</button><span>{track.artist}</span></div></div></td>
      <td className="album-cell">{track.album || '—'}</td><td className="year-cell">{track.release_date?.slice(0, 4) || '—'}</td>
      <td className="save-cell"><IconButton label={liked.has(track.track_id) ? `Hapus ${track.title} dari favorit` : `Sukai ${track.title}`} active={liked.has(track.track_id)} onClick={() => onLike(track)}>{liked.has(track.track_id) ? <Check size={16} /> : <Plus size={16} />}</IconButton></td>
      <td className="duration-cell">{duration(track.duration_ms)}</td><td className="menu-cell"><IconButton label={`Tambahkan ${track.title} ke playlist`} onClick={() => onAdd(track)}><MoreHorizontal size={19} /></IconButton></td>
    </tr>)}</tbody>
  </table></div>
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close() }, [])
  return <dialog ref={ref} className="modal" onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <header><h2>{title}</h2><IconButton label="Tutup dialog" onClick={onClose}><X size={22} /></IconButton></header>{children}
  </dialog>
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Music2 size={36} /></div><h2>{title}</h2><p>{children}</p></div>
}

export function LikedArt({ small = false }: { small?: boolean }) {
  return <div className={`liked-art ${small ? 'small' : ''}`}><Heart fill="currentColor" size={small ? 21 : 68} strokeWidth={0} /></div>
}
