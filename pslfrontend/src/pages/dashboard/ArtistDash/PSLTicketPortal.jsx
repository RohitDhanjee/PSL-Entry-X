/**
 * PSL Entry X Portal
 * ==========================
 * Hackathon Demo: Dynamic QR-based stadium entry system.
 * 
 * Features:
 * - View purchased PSL tickets
 * - Reveal dynamic QR code (60-second expiry)
 * - Auto-refresh QR before expiry
 * - Visual countdown timer
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Ticket,
  QrCode,
  Shield,
  Clock,
  CheckCircle,
  XCircle,
  MapPin,
  Calendar,
  Users,
  Loader2,
  AlertTriangle,
  ChevronRight,
  Smartphone,
  Pencil,
  Trash2,
  X
} from "lucide-react";
import { useAuth } from "../../../context/AuthContext";
import { pslAPI, ticketsAPI } from "../../../services/api";
import LoadingSpinner from "../../../components/common/LoadingSpinner";
import toast from "react-hot-toast";

const AUTHORIZED_PSL_ISSUERS = ["rohitdhanjee25@gmail.com", "admin@pslentryx.com"];
const API_BASE_URL = import.meta.env.VITE_BASE_URL_BACKEND || "http://localhost:8000";
const BACKEND_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");

const normalizeTicketImageSource = (source) => {
  if (!source || typeof source !== "string") return "";

  const value = source.trim();
  if (!value) return "";

  // Metadata JSON links are not directly renderable in an <img> tag.
  if (value.includes("metadata.json")) return "";

  if (value.startsWith("data:")) return value;
  if (value.startsWith("ipfs://")) {
    return `https://ipfs.io/ipfs/${value.replace("ipfs://", "")}`;
  }
  if (/^https?:\/\//i.test(value)) return value;
  if (/^(Qm|bafy|bafk)/i.test(value)) return `https://ipfs.io/ipfs/${value}`;
  if (value.startsWith("/")) return `${BACKEND_ORIGIN}${value}`;
  if (value.startsWith("api/")) return `${BACKEND_ORIGIN}/${value}`;

  return value;
};

const formatMatchDate = (matchDateTime) => {
  if (!matchDateTime) return "";
  const parsed = new Date(matchDateTime);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString();
};

const formatMatchTime12Hour = (matchDateTime) => {
  if (!matchDateTime || typeof matchDateTime !== "string") return "";

  // Avoid fake 12:00 AM when input contains only date without a time component.
  const hasExplicitTime = /T\d{1,2}:\d{2}|\d{1,2}:\d{2}/.test(matchDateTime);
  if (!hasExplicitTime) return "";

  const parsed = new Date(matchDateTime);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
  }

  // Fallback for plain HH:mm strings.
  const timeMatch = matchDateTime.match(/(\d{1,2}):(\d{2})/);
  if (!timeMatch) return "";

  const hour24 = Number(timeMatch[1]);
  const minute = timeMatch[2];
  if (Number.isNaN(hour24) || hour24 < 0 || hour24 > 23) return "";

  const suffix = hour24 >= 12 ? "PM" : "AM";
  const hour12 = hour24 % 12 || 12;
  return `${hour12}:${minute} ${suffix}`;
};

const splitMatchDateTime = (matchDateTime) => {
  if (!matchDateTime || typeof matchDateTime !== "string") {
    return { matchDate: "", matchTime: "" };
  }

  const isoMatch = matchDateTime.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})/);
  if (isoMatch) {
    return { matchDate: isoMatch[1], matchTime: isoMatch[2] };
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(matchDateTime)) {
    return { matchDate: matchDateTime, matchTime: "" };
  }

  return { matchDate: "", matchTime: "" };
};

const PSLTicketPortal = () => {
  const { isAuthenticated, user } = useAuth();
  const isAuthorizedIssuer = !!user?.email && AUTHORIZED_PSL_ISSUERS.includes(user.email.toLowerCase());
  
  // State
  const [tickets, setTickets] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [qrData, setQrData] = useState(null);
  const [isRevealLoading, setIsRevealLoading] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState(null);

  // Resale toggle state
  const [resaleUpdatingTicketId, setResaleUpdatingTicketId] = useState(null);
  const [editingTicket, setEditingTicket] = useState(null);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [deleteLoadingTicketId, setDeleteLoadingTicketId] = useState(null);
  
  // Refs for intervals
  const countdownRef = useRef(null);
  const autoRefreshRef = useRef(null);

  // Fetch user's PSL tickets
  const fetchTickets = useCallback(async () => {
    // Don't fetch if not authenticated or user is not loaded yet
    if (!isAuthenticated || !user) {
      setIsLoading(false);
      return;
    }
    
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await pslAPI.getMyTickets();
      setTickets(response?.data || []);
    } catch (err) {
      console.error("Failed to fetch tickets:", err);
      // Don't show error for 401 - interceptor handles logout
      if (err.response?.status !== 401) {
        setError("Failed to load tickets. Please try again.");
        toast.error("Failed to load tickets");
      }
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated, user]);

  // Reveal QR code for a ticket
  const revealQR = useCallback(async (ticket) => {
    if (isAuthorizedIssuer) {
      return;
    }

    // For owners, license_id might be null - use ticket_id instead
    const licenseId = ticket.license_id || ticket.ticket_id;
    
    setIsRevealLoading(true);
    setSelectedTicket(ticket);
    
    try {
      const response = await pslAPI.revealTicket({
        license_id: licenseId,
        ticket_id: ticket.ticket_id
      });
      
      setQrData(response.data);
      setCountdown(response.data.seconds_remaining);
      toast.success("🎫 QR Code revealed!");
      
      // Start countdown
      startCountdown(response.data.seconds_remaining);
      
    } catch (err) {
      console.error("Failed to reveal QR:", err);
      const errorMsg = err.response?.data?.detail || err.message || "Failed to reveal ticket";
      toast.error(errorMsg);
      setSelectedTicket(null);
    } finally {
      setIsRevealLoading(false);
    }
  }, [isAuthorizedIssuer]);

  // Start countdown timer
  const startCountdown = (seconds) => {
    // Clear existing interval
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
    }
    
    setCountdown(seconds);
    
    countdownRef.current = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          // Auto-refresh QR when timer hits 0
          if (selectedTicket) {
            refreshQR();
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // Refresh QR code
  const refreshQR = useCallback(async () => {
    if (!selectedTicket) return;
    
    // For owners, license_id might be null - use ticket_id instead
    const licenseId = selectedTicket.license_id || selectedTicket.ticket_id;
    
    try {
      const response = await pslAPI.revealTicket({
        license_id: licenseId,
        ticket_id: selectedTicket.ticket_id
      });
      
      setQrData(response.data);
      setCountdown(response.data.seconds_remaining);
      startCountdown(response.data.seconds_remaining);
      
    } catch (err) {
      console.error("Failed to refresh QR:", err);
      const errorMsg = err.response?.data?.detail || err.message || "Failed to refresh QR. Please try again.";
      toast.error(errorMsg);
    }
  }, [selectedTicket]);

  // Close QR modal
  const closeQRModal = () => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
    }
    setSelectedTicket(null);
    setQrData(null);
    setCountdown(0);
  };

  // Toggle resale visibility in Explorer
  const handleResaleToggle = async (ticket) => {
    if (!ticket?.ticket_id) return;

    if (!ticket?.is_secondary_owner) {
      toast.error("Resale option is only available for secondary owners.");
      return;
    }

    if (ticket.is_redeemed) {
      toast.error("Used ticket cannot be listed for resale");
      return;
    }

    const currentPrice = Number(ticket.price || 0);
    if (!ticket.is_for_sale && (!Number.isFinite(currentPrice) || currentPrice <= 0)) {
      toast.error("Ticket price missing. Please set a valid price before enabling resale.");
      return;
    }

    setResaleUpdatingTicketId(ticket.ticket_id);
    try {
      if (ticket.is_for_sale) {
        await ticketsAPI.delist(ticket.ticket_id);
        setTickets((prev) => prev.map((t) => (
          t.ticket_id === ticket.ticket_id ? { ...t, is_for_sale: false } : t
        )));
        window.dispatchEvent(new CustomEvent("ticket-cache-invalidated"));
        toast.success("Resale disabled. Ticket removed from Explorer.");
      } else {
        await ticketsAPI.listForSale(ticket.ticket_id, currentPrice);
        setTickets((prev) => prev.map((t) => (
          t.ticket_id === ticket.ticket_id ? { ...t, is_for_sale: true } : t
        )));
        window.dispatchEvent(new CustomEvent("ticket-cache-invalidated"));
        toast.success("Resale enabled. Ticket is now visible on Explorer.");
      }
    } catch (err) {
      console.error("Resale toggle failed:", err);
      toast.error(err?.message || "Failed to update resale status");
    } finally {
      setResaleUpdatingTicketId(null);
    }
  };

  const openEditModal = (ticket) => {
    const split = splitMatchDateTime(ticket.match_datetime);
    setEditingTicket({
      ticket_id: ticket.ticket_id,
      title: ticket.title || "",
      match_info: ticket.match_info || "",
      seat_number: ticket.seat_number || "",
      stand: ticket.stand || "",
      venue: ticket.venue || "",
      match_date: split.matchDate,
      match_time: split.matchTime,
      price: ticket.price ?? "",
    });
  };

  const handleSaveIssuerEdit = async (formData) => {
    if (!editingTicket?.ticket_id) return;

    setIsSavingEdit(true);
    try {
      const response = await pslAPI.updateTicket(editingTicket.ticket_id, formData);
      const updated = response?.data;

      if (updated?.ticket_id) {
        setTickets((prev) => prev.map((t) => (
          t.ticket_id === updated.ticket_id
            ? { ...t, ...updated }
            : t
        )));
      }

      setEditingTicket(null);
      toast.success("Ticket updated successfully");
    } catch (err) {
      console.error("Failed to update ticket:", err);
      toast.error(err?.response?.data?.detail || "Failed to update ticket");
    } finally {
      setIsSavingEdit(false);
    }
  };

  const handleIssuerDelete = async (ticket) => {
    if (!ticket?.ticket_id) return;

    const confirmed = window.confirm("Are you sure you want to delete this ticket record?");
    if (!confirmed) return;

    setDeleteLoadingTicketId(ticket.ticket_id);
    try {
      await pslAPI.deleteTicket(ticket.ticket_id);
      setTickets((prev) => prev.filter((t) => t.ticket_id !== ticket.ticket_id));
      if (editingTicket?.ticket_id === ticket.ticket_id) {
        setEditingTicket(null);
      }
      toast.success("Ticket deleted successfully");
    } catch (err) {
      console.error("Failed to delete ticket:", err);
      toast.error(err?.response?.data?.detail || "Failed to delete ticket");
    } finally {
      setDeleteLoadingTicketId(null);
    }
  };

  // Effects
  useEffect(() => {
    fetchTickets();
  }, [fetchTickets]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current);
      if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
    };
  }, []);

  // Format countdown display
  const formatCountdown = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Get countdown color based on time remaining
  const getCountdownColor = (seconds) => {
    if (seconds <= 10) return "text-red-500";
    if (seconds <= 30) return "text-yellow-500";
    return "text-green-500";
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-gradient-to-r from-green-500 to-emerald-600 rounded-lg">
            <Ticket className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-slate-900">PSL Entry X Portal</h1>
          <span className="px-3 py-1 bg-amber-100 text-amber-700 text-xs font-semibold rounded-full border border-amber-200">
            DEMO
          </span>
        </div>
        <p className="text-slate-600 text-base">
          {isAuthorizedIssuer
            ? "Your uploaded PSL ticket records"
            : "Your secure PSL match tickets with DRM-protected entry passes"}
        </p>
      </div>

      {/* Security Banner */}
      {isAuthorizedIssuer ? (
        <div className="mb-6 p-4 bg-gradient-to-r from-emerald-50 to-green-50 border border-emerald-200 rounded-2xl shadow-sm">
          <div className="flex items-start gap-3">
            <Ticket className="w-5 h-5 text-emerald-600 mt-0.5" />
            <div>
              <h3 className="text-sm font-semibold text-emerald-700">Issuer Record View</h3>
              <p className="text-sm text-slate-600 mt-1">
                You are viewing uploaded PSL ticket records. QR reveal is disabled for authorized uploaders.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="mb-6 p-5 bg-gradient-to-r from-sky-50 to-indigo-50 border border-sky-200 rounded-2xl shadow-sm">
          <div className="flex items-start gap-3">
            <Shield className="w-5 h-5 text-sky-600 mt-0.5" />
            <div>
              <h3 className="text-lg font-semibold text-sky-700">Dynamic QR Protection</h3>
              <p className="text-sm text-slate-600 mt-1">
                Your entry QR code refreshes every 60 seconds. Screenshots become useless - 
                only the verified owner can reveal a valid code at the gate.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-xl">
          <div className="flex items-center gap-2 text-red-400">
            <AlertTriangle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Tickets Grid */}
      {tickets.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-2xl border border-slate-200 shadow-sm">
          <Ticket className="w-16 h-16 text-slate-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-slate-700 mb-2">No Tickets Found</h3>
          <p className="text-slate-500 text-sm">
            Your purchased or uploaded PSL tickets will appear here
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {tickets.map((ticket) => (
            <TicketCard 
              key={ticket.ticket_id}
              ticket={ticket}
              onReveal={() => revealQR(ticket)}
              onToggleResale={() => handleResaleToggle(ticket)}
              onEdit={() => openEditModal(ticket)}
              onDelete={() => handleIssuerDelete(ticket)}
              isAuthorizedIssuer={isAuthorizedIssuer}
              isResaleUpdating={resaleUpdatingTicketId === ticket.ticket_id}
              isDeleteLoading={deleteLoadingTicketId === ticket.ticket_id}
              isLoading={isRevealLoading && selectedTicket?.ticket_id === ticket.ticket_id}
            />
          ))}
        </div>
      )}

      {/* QR Reveal Modal */}
      {!isAuthorizedIssuer && selectedTicket && qrData && (
        <QRRevealModal
          ticket={selectedTicket}
          qrData={qrData}
          countdown={countdown}
          onClose={closeQRModal}
          onRefresh={refreshQR}
          formatCountdown={formatCountdown}
          getCountdownColor={getCountdownColor}
        />
      )}

      {isAuthorizedIssuer && editingTicket && (
        <IssuerTicketEditModal
          ticket={editingTicket}
          onClose={() => setEditingTicket(null)}
          onSave={handleSaveIssuerEdit}
          isSaving={isSavingEdit}
        />
      )}

    </div>
  );
};

// Ticket Card Component
const TicketCard = ({
  ticket,
  onReveal,
  onToggleResale,
  onEdit,
  onDelete,
  isLoading,
  isAuthorizedIssuer,
  isResaleUpdating,
  isDeleteLoading,
}) => {
  const isRedeemed = ticket.is_redeemed;
  const isIssuerView = isAuthorizedIssuer === true;
  const isOwnershipTransferred = Boolean(ticket.is_secondary_owner);
  const issuerCanEdit = isIssuerView && !isRedeemed;
  const issuerCanDelete = isIssuerView && !isRedeemed;
  const issuerLockReason = isRedeemed
    ? "Ticket already redeemed"
    : "Record locked";
  const canShowResaleToggle = !isIssuerView && !isRedeemed && Boolean(ticket.is_secondary_owner);
  const [imageFailed, setImageFailed] = useState(false);
  const normalizedImageUrl = !imageFailed
    ? normalizeTicketImageSource(ticket.image_url || ticket.metadata_uri)
    : "";
  const matchTime = formatMatchTime12Hour(ticket.match_datetime);
  
  return (
    <div className={`
      relative overflow-hidden rounded-2xl border transition-all duration-300
      ${isRedeemed 
        ? 'bg-slate-100 border-slate-200 opacity-70' 
        : 'bg-white border-slate-200 hover:border-emerald-300 hover:shadow-xl hover:shadow-emerald-100/70'
      }
    `}>
      {/* Ticket Image */}
      <div className="relative h-52 bg-gradient-to-br from-emerald-500 to-green-600 overflow-hidden">
        {normalizedImageUrl ? (
          <img 
            src={normalizedImageUrl}
            alt={ticket.title}
            className="w-full h-full object-cover"
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-white/80 bg-gradient-to-br from-emerald-500 to-green-700">
            <Ticket className="w-14 h-14 text-white/70 mb-2" />
            <p className="text-sm font-medium px-4 text-center truncate w-full">{ticket.title || "PSL Match Ticket"}</p>
          </div>
        )}

        <div className="absolute inset-0 bg-gradient-to-t from-black/15 via-transparent to-transparent" />
        
        {/* Status Badge */}
        <div className={`
          absolute top-3 right-3 px-3 py-1 rounded-full text-xs font-semibold
          ${isRedeemed 
            ? 'bg-slate-800/85 text-slate-200' 
            : 'bg-emerald-500/95 text-white'
          }
        `}>
          {isRedeemed ? 'Used' : 'Valid'}
        </div>
      </div>

      {/* Ticket Info */}
      <div className="p-4">
        <h3 className="font-semibold text-slate-900 mb-2 truncate">{ticket.title}</h3>
        
        <div className="space-y-2 text-sm text-slate-600 mb-4">
          {ticket.match_info && (
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-emerald-600" />
              <span className="truncate">{ticket.match_info}</span>
            </div>
          )}
          {ticket.seat_number && (
            <div className="flex items-center gap-2">
              <MapPin className="w-4 h-4 text-emerald-600" />
              <span>Seat {ticket.seat_number} {ticket.stand && `• ${ticket.stand}`}</span>
            </div>
          )}
          {ticket.match_datetime && (
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 text-emerald-600" />
              <span>{formatMatchDate(ticket.match_datetime)}</span>
            </div>
          )}
          {matchTime && (
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-emerald-600" />
              <span>{matchTime}</span>
            </div>
          )}
        </div>

        {/* Action */}
        {isIssuerView ? (
          <div className="space-y-2">
            <div className="w-full py-2.5 px-4 rounded-xl font-medium bg-slate-100 text-slate-600 text-center border border-slate-200">
              Uploaded Ticket Record
            </div>
            {issuerCanEdit ? (
              <div className={`grid ${issuerCanDelete ? 'grid-cols-2' : 'grid-cols-1'} gap-2`}>
                <button
                  onClick={onEdit}
                  disabled={isDeleteLoading}
                  className="w-full py-2.5 px-3 rounded-xl text-sm font-semibold border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors flex items-center justify-center gap-2 disabled:opacity-60"
                >
                  <Pencil className="w-4 h-4" />
                  Edit
                </button>
                {issuerCanDelete && (
                  <button
                    onClick={onDelete}
                    disabled={isDeleteLoading}
                    className="w-full py-2.5 px-3 rounded-xl text-sm font-semibold border border-red-200 bg-red-50 text-red-700 hover:bg-red-100 transition-colors flex items-center justify-center gap-2 disabled:opacity-60"
                  >
                    {isDeleteLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    Delete
                  </button>
                )}
              </div>
            ) : (
              <div className="w-full rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800 text-center">
                {issuerLockReason}
              </div>
            )}
            {isOwnershipTransferred && isIssuerView && (
              <div className="w-full rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800 text-center">
                Ownership transferred on blockchain. Organizer can still edit or delete this record.
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2 relative">
            <button
              onClick={onReveal}
              disabled={isRedeemed || isLoading}
              className={`
                w-full py-3 px-4 rounded-xl font-medium transition-all duration-200
                flex items-center justify-center gap-2
                ${isRedeemed
                  ? 'bg-slate-200 text-slate-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-emerald-500 to-green-600 text-white hover:from-emerald-600 hover:to-green-700 hover:shadow-lg hover:shadow-emerald-200'
                }
              `}
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Verifying...</span>
                </>
              ) : isRedeemed ? (
                <>
                  <XCircle className="w-4 h-4" />
                  <span>Already Used</span>
                </>
              ) : (
                <>
                  <QrCode className="w-4 h-4" />
                  <span>Reveal Pass</span>
                  <ChevronRight className="w-4 h-4" />
                </>
              )}
            </button>

            {canShowResaleToggle && (
              <div className="w-full rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5">
                <button
                  onClick={onToggleResale}
                  disabled={isLoading || isResaleUpdating}
                  className="w-full flex items-center justify-between gap-3 disabled:opacity-60"
                >
                  <div className="text-left">
                    <p className="text-sm font-semibold text-emerald-800">Resale on Explorer</p>
                    <p className="text-xs text-emerald-700">
                      {ticket.is_for_sale ? "Visible for buyers" : "Hidden from buyers"}
                    </p>
                  </div>

                  <span
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      ticket.is_for_sale ? "bg-emerald-600" : "bg-slate-300"
                    }`}
                    aria-label="Toggle resale"
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        ticket.is_for_sale ? "translate-x-6" : "translate-x-1"
                      }`}
                    />
                  </span>
                </button>
                <p className="mt-2 text-[11px] text-emerald-700">
                  {isResaleUpdating ? "Updating..." : "Turn on to show this ticket in Explorer for resale purchases."}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const IssuerTicketEditModal = ({ ticket, onClose, onSave, isSaving }) => {
  const [form, setForm] = useState({
    title: ticket.title || "",
    match_info: ticket.match_info || "",
    seat_number: ticket.seat_number || "",
    stand: ticket.stand || "",
    venue: ticket.venue || "",
    match_date: ticket.match_date || "",
    match_time: ticket.match_time || "",
    price: ticket.price ?? "",
  });

  const onChange = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave({
      title: form.title,
      match_info: form.match_info,
      seat_number: form.seat_number,
      stand: form.stand,
      venue: form.venue,
      match_date: form.match_date,
      match_time: form.match_time,
      price: form.price === "" ? null : Number(form.price),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <h3 className="text-lg font-semibold text-slate-900">Edit Ticket Record</h3>
          <button
            onClick={onClose}
            disabled={isSaving}
            className="p-2 rounded-lg text-slate-500 hover:bg-slate-100"
            aria-label="Close edit modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Match Title</label>
            <input
              type="text"
              value={form.title}
              onChange={(e) => onChange("title", e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Match Info</label>
            <textarea
              rows={3}
              value={form.match_info}
              onChange={(e) => onChange("match_info", e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Seat Number</label>
              <input
                type="text"
                value={form.seat_number}
                onChange={(e) => onChange("seat_number", e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Stand / Enclosure</label>
              <input
                type="text"
                value={form.stand}
                onChange={(e) => onChange("stand", e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Venue</label>
              <input
                type="text"
                value={form.venue}
                onChange={(e) => onChange("venue", e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Match Date</label>
              <input
                type="date"
                value={form.match_date}
                onChange={(e) => onChange("match_date", e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Match Time</label>
              <input
                type="time"
                value={form.match_time}
                onChange={(e) => onChange("match_time", e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Ticket Price</label>
            <input
              type="number"
              min="0"
              step="any"
              value={form.price}
              onChange={(e) => onChange("price", e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
            />
          </div>

          <div className="pt-2 flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="px-4 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60 flex items-center gap-2"
            >
              {isSaving && <Loader2 className="w-4 h-4 animate-spin" />}
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// QR Reveal Modal Component
const QRRevealModal = ({ 
  ticket, 
  qrData, 
  countdown, 
  onClose, 
  onRefresh,
  formatCountdown,
  getCountdownColor 
}) => {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="bg-gray-900 rounded-3xl max-w-md w-full overflow-hidden border border-gray-700/50 shadow-2xl">
        {/* Header */}
        <div className="p-6 bg-gradient-to-r from-green-500 to-emerald-600 text-white">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold">Entry Pass</h2>
              <p className="text-sm text-green-100 opacity-80">{ticket.title}</p>
            </div>
            <div className="p-2 bg-white/20 rounded-full">
              <Ticket className="w-6 h-6" />
            </div>
          </div>
        </div>

        {/* QR Code Section */}
        <div className="p-6 flex flex-col items-center">
          {/* Countdown Timer */}
          <div className={`
            flex items-center gap-2 mb-4 px-4 py-2 rounded-full
            ${countdown <= 10 ? 'bg-red-500/20' : countdown <= 30 ? 'bg-yellow-500/20' : 'bg-green-500/20'}
          `}>
            <Clock className={`w-5 h-5 ${getCountdownColor(countdown)}`} />
            <span className={`font-mono text-xl font-bold ${getCountdownColor(countdown)}`}>
              {formatCountdown(countdown)}
            </span>
          </div>

          {/* QR Code */}
          <div className="bg-white p-4 rounded-2xl shadow-lg mb-4">
            <img 
              src={qrData.qr_code} 
              alt="Entry QR Code"
              className="w-48 h-48"
            />
          </div>

          {/* Security Notice */}
          <div className="flex items-center gap-2 text-xs text-gray-400 mb-4">
            <Shield className="w-4 h-4 text-green-500" />
            <span>QR refreshes automatically • Screenshots won't work</span>
          </div>

          {/* Ticket Details */}
          <div className="w-full p-4 bg-gray-800/50 rounded-xl mb-4">
            <div className="grid grid-cols-2 gap-3 text-sm">
              {ticket.seat_number && (
                <div>
                  <span className="text-gray-500">Seat</span>
                  <p className="text-white font-medium">{ticket.seat_number}</p>
                </div>
              )}
              {ticket.stand && (
                <div>
                  <span className="text-gray-500">Stand</span>
                  <p className="text-white font-medium">{ticket.stand}</p>
                </div>
              )}
            </div>
          </div>

          {/* Instructions */}
          <div className="w-full p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl mb-4">
            <div className="flex items-start gap-2">
              <Smartphone className="w-4 h-4 text-blue-400 mt-0.5" />
              <p className="text-xs text-blue-300">
                Show this QR to the gate scanner. Keep your screen bright and steady.
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="w-full flex gap-3">
            <button
              onClick={onRefresh}
              className="flex-1 h-12 px-4 bg-slate-600 hover:bg-slate-500 active:bg-slate-400 text-white rounded-xl font-semibold border border-slate-400/20 shadow-md transition-all duration-200 flex items-center justify-center gap-2"
            >
              <RefreshCw className="w-4 h-4 text-white" />
              <span className="text-white">Refresh</span>
            </button>
            <button
              onClick={onClose}
              className="flex-1 h-12 px-4 bg-rose-600 hover:bg-rose-500 active:bg-rose-400 text-white rounded-xl font-semibold border border-rose-300/20 shadow-md transition-all duration-200 flex items-center justify-center"
            >
              <span className="text-white">Close</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PSLTicketPortal;
