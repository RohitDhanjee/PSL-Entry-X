import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Ticket, QrCode, UploadCloud, ScanLine, CalendarClock, CheckCircle2 } from 'lucide-react';
import { pslAPI } from '../../../services/api';
import { useAuth } from '../../../context/AuthContext';

const AUTHORIZED_PSL_ISSUERS = ['rohitdhanjee25@gmail.com', 'admin@pslentryx.com'];

const DashboardHome = () => {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const isAuthorizedIssuer = useMemo(() => {
    const email = user?.email?.toLowerCase();
    return !!email && AUTHORIZED_PSL_ISSUERS.includes(email);
  }, [user?.email]);

  const loadPslTickets = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await pslAPI.getMyTickets();
      setTickets(response?.data || []);
    } catch (err) {
      setError(err?.message || 'Failed to load PSL dashboard data.');
      setTickets([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPslTickets();
  }, [loadPslTickets]);

  const normalized = useMemo(() => {
    return (tickets || []).map((t) => {
      const dt = t?.match_datetime ? new Date(t.match_datetime) : null;
      return {
        ...t,
        parsedDate: dt instanceof Date && !Number.isNaN(dt.valueOf()) ? dt : null,
      };
    });
  }, [tickets]);

  const now = Date.now();

  const summary = useMemo(() => {
    const total = normalized.length;
    const redeemed = normalized.filter((t) => t.is_redeemed === true).length;
    const readyForReveal = normalized.filter((t) => t.can_reveal === true && t.is_redeemed !== true).length;
    const upcoming = normalized.filter((t) => t.parsedDate && t.parsedDate.getTime() > now).length;
    return { total, redeemed, readyForReveal, upcoming };
  }, [normalized, now]);

  const nextMatch = useMemo(() => {
    const upcoming = normalized
      .filter((t) => t.parsedDate && t.parsedDate.getTime() > now)
      .sort((a, b) => a.parsedDate - b.parsedDate);
    return upcoming[0] || null;
  }, [normalized, now]);

  const cards = isAuthorizedIssuer
    ? [
        { label: 'PSL Tickets Uploaded', value: summary.total, icon: UploadCloud },
        { label: 'Upcoming Match Slots', value: summary.upcoming, icon: CalendarClock },
        { label: 'Redeemed at Gate', value: summary.redeemed, icon: CheckCircle2 },
      ]
    : [
        { label: 'PSL Tickets Owned', value: summary.total, icon: Ticket },
        { label: 'Ready for QR Reveal', value: summary.readyForReveal, icon: QrCode },
        { label: 'Already Used', value: summary.redeemed, icon: CheckCircle2 },
      ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-emerald-50 p-4 md:p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">
              {isAuthorizedIssuer ? 'PSL Issuer Dashboard' : 'PSL Fan Dashboard'}
            </h1>
            <p className="text-slate-600 mt-2">
              {isAuthorizedIssuer
                ? 'Track uploaded PSL tickets, event readiness, and gate redemption status.'
                : 'Manage your PSL tickets and reveal secure QR entry passes.'}
            </p>
          </div>

          <div className="flex items-center gap-3">
            {isAuthorizedIssuer && (
              <button
                onClick={() => navigate('/dashboard/upload')}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium transition-colors"
              >
                Upload PSL Ticket
              </button>
            )}
            <button
              onClick={loadPslTickets}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-900 hover:bg-black text-white font-medium transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Refresh
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-8">
          {cards.map((card) => {
            const Icon = card.icon;
            return (
              <div key={card.label} className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                <div className="flex justify-between items-start">
                  <p className="text-sm font-medium text-slate-600">{card.label}</p>
                  <Icon className="w-5 h-5 text-emerald-600" />
                </div>
                <p className="mt-3 text-3xl font-bold text-slate-900">{loading ? '...' : card.value}</p>
              </div>
            );
          })}
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm mb-8">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
            <h2 className="text-xl font-semibold text-slate-900">PSL Tickets Snapshot</h2>
            <button
              onClick={() => navigate('/dashboard/psl-tickets')}
              className="text-emerald-700 hover:text-emerald-800 text-sm font-semibold"
            >
              Open PSL Ticket Hub
            </button>
          </div>

          {!loading && normalized.length === 0 && (
            <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-slate-500">
              {isAuthorizedIssuer
                ? 'No PSL ticket records yet. Start by uploading your first PSL ticket.'
                : 'No PSL tickets in your account yet.'}
            </div>
          )}

          {loading && (
            <div className="text-slate-500 py-6">Loading PSL tickets...</div>
          )}

          {!loading && normalized.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {normalized.slice(0, 4).map((t) => (
                <div key={t.ticket_id} className="rounded-lg border border-slate-200 p-4 bg-slate-50">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-900 truncate">{t.title || 'PSL Match Ticket'}</p>
                      <p className="text-sm text-slate-600 mt-1">Seat {t.seat_number || '-'} | {t.stand || '-'}</p>
                      <p className="text-xs text-slate-500 mt-1">{t.match_info || 'Match details unavailable'}</p>
                    </div>
                    <span className={`text-xs px-2 py-1 rounded-full ${t.is_redeemed ? 'bg-slate-200 text-slate-700' : 'bg-emerald-100 text-emerald-700'}`}>
                      {t.is_redeemed ? 'Redeemed' : 'Active'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center gap-2 mb-2">
              <CalendarClock className="w-5 h-5 text-emerald-600" />
              <h3 className="font-semibold text-slate-900">Next Match</h3>
            </div>
            {nextMatch ? (
              <>
                <p className="text-slate-800 font-medium">{nextMatch.title || 'PSL Match Ticket'}</p>
                <p className="text-slate-600 text-sm mt-1">Seat {nextMatch.seat_number || '-'} | {nextMatch.stand || '-'}</p>
                <p className="text-slate-500 text-sm mt-1">
                  {nextMatch.parsedDate ? nextMatch.parsedDate.toLocaleString() : 'Date TBA'}
                </p>
              </>
            ) : (
              <p className="text-slate-500 text-sm">No upcoming PSL match found.</p>
            )}
          </div>

          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center gap-2 mb-2">
              {isAuthorizedIssuer ? <ScanLine className="w-5 h-5 text-emerald-600" /> : <QrCode className="w-5 h-5 text-emerald-600" />}
              <h3 className="font-semibold text-slate-900">Quick Action</h3>
            </div>
            <p className="text-slate-600 text-sm mb-4">
              {isAuthorizedIssuer
                ? 'Use scanner mode for secure gate entry validation and live redemption control.'
                : 'Open your PSL Ticket Hub to reveal QR and access your entry passes.'}
            </p>
            <button
              onClick={() => navigate(isAuthorizedIssuer ? '/dashboard/gate-scanner' : '/dashboard/psl-tickets')}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium transition-colors"
            >
              {isAuthorizedIssuer ? 'Open Gate Scanner' : 'Open PSL Ticket Hub'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DashboardHome;