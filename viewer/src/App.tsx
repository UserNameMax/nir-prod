import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { ObjectList } from './pages/ObjectList'
import { ObjectCalendar } from './pages/ObjectCalendar'
import { DayView } from './pages/DayView'
import { IngestPage } from './pages/IngestPage'
import { GlobalCalendar } from './pages/GlobalCalendar'
import { DayObjects } from './pages/DayObjects'
import { AlertQueue } from './pages/AlertQueue'
import { WatchList } from './pages/WatchList'
import { ObjectDrilldown } from './pages/ObjectDrilldown'
import { KpiPanel } from './pages/KpiPanel'

function Nav() {
  const base = 'px-4 py-2 text-sm rounded-lg transition-colors'
  const active = `${base} bg-blue-500 text-white`
  const inactive = `${base} text-slate-600 hover:bg-slate-100`

  return (
    <nav className="border-b border-slate-200 bg-white px-6 py-3 flex items-center gap-2">
      <span className="font-semibold text-slate-800 mr-4">ЦТП Monitor</span>
      <NavLink to="/" end className={({ isActive }) => isActive ? active : inactive}>
        Очередь
      </NavLink>
      <NavLink to="/watchlist" className={({ isActive }) => isActive ? active : inactive}>
        Хроника
      </NavLink>
      <NavLink to="/kpi" className={({ isActive }) => isActive ? active : inactive}>
        Качество
      </NavLink>
      <span className="w-px h-5 bg-slate-200 mx-2" />
      <NavLink to="/objects" className={({ isActive }) => isActive ? active : inactive}>
        Объекты
      </NavLink>
      <NavLink to="/calendar" className={({ isActive }) => isActive ? active : inactive}>
        Календарь
      </NavLink>
      <NavLink to="/ingest" className={({ isActive }) => isActive ? active : inactive}>
        Загрузка данных
      </NavLink>
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="h-screen flex flex-col bg-slate-50">
        <Nav />
        <div className="flex-1 min-h-0 overflow-auto">
        <Routes>
          {/* Предиктивный контур */}
          <Route path="/" element={<AlertQueue />} />
          <Route path="/watchlist" element={<WatchList />} />
          <Route path="/risk/:object_id" element={<ObjectDrilldown />} />
          <Route path="/kpi" element={<KpiPanel />} />
          {/* Просмотр данных */}
          <Route path="/objects" element={<ObjectList />} />
          <Route path="/calendar" element={<GlobalCalendar />} />
          <Route path="/calendar/:date" element={<DayObjects />} />
          <Route path="/object/:object_id" element={<ObjectCalendar />} />
          <Route path="/object/:object_id/day/:date" element={<DayView />} />
          <Route path="/ingest" element={<IngestPage />} />
        </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}
