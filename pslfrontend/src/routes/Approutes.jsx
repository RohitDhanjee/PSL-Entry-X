import React from 'react'
import Auth from '../pages/Auth'
import { Routes, Route, Navigate } from 'react-router-dom'
import Home from '../pages/Home'
import MainLayout from './Layout'
import ArtistDash from '../pages/dashboard/ArtistDash/ArtistDash'
import Wallets from '../pages/dashboard/ArtistDash/Wallet'
import Settings from '../pages/dashboard/ArtistDash/Settings'
import DashboardHome from '../pages/dashboard/ArtistDash/DashboardHome'
import PSLTicketPortal from '../pages/dashboard/ArtistDash/PSLTicketPortal'
import GateScanner from '../pages/dashboard/ArtistDash/GateScanner'
import UploadTickets from '../pages/dashboard/ArtistDash/UploadTickets'
import ScrollRestore from '../components/ScrollRestore'
import ProtectedRoute from './ProtectedRoutes'
import { useAuth } from '../context/AuthContext'

import Explorer from '../pages/Explorer'
import SalePage from '../pages/SalePage'
import TicketDetail from '../pages/TicketDetail'
import OAuthCallback from '../pages/OAuthCallback'

const AUTHORIZED_PSL_ISSUERS = ['rohitdhanjee25@gmail.com', 'admin@pslentryx.com']

const IssuerOnlyRoute = ({ children }) => {
    const { user } = useAuth()
    const email = user?.email?.toLowerCase()
    const isAuthorizedIssuer = !!email && AUTHORIZED_PSL_ISSUERS.includes(email)

    if (!isAuthorizedIssuer) {
        return <Navigate to="/dashboard" replace />
    }

    return children
}

const AppRoutes = () => {
    return (
        <>
            <ScrollRestore />
            <Routes>
                {/* All routes use MainLayout for consistent navbar/footer */}
                <Route path="/" element={<MainLayout />}>
                    {/* Public routes */}
                    <Route index element={<Home />} />
                    <Route path="auth" element={<Auth />} />
                    <Route path="explorer" element={<Explorer />} />
                    <Route path="sale/:artworkId" element={<SalePage />} />
                    <Route path="ticket/:artworkId" element={<TicketDetail />} />
                    <Route path="/auth/callback" element={<OAuthCallback />} />

                    {/* User Dashboard routes with MainLayout */}
                    <Route 
                        path="dashboard" 
                        element={
                            <ProtectedRoute>
                                <ArtistDash />
                            </ProtectedRoute>
                        }
                    >
                        {/* Default dashboard route */}
                        <Route index element={<DashboardHome />} />
                        <Route path="home" element={<DashboardHome />} />
                        <Route path="psl-tickets" element={<PSLTicketPortal />} />
                        <Route path="upload" element={<IssuerOnlyRoute><UploadTickets /></IssuerOnlyRoute>} />
                        <Route path="gate-scanner" element={<IssuerOnlyRoute><GateScanner /></IssuerOnlyRoute>} />
                        <Route path="wallet" element={<Wallets />} />
                        <Route path="settings" element={<Settings />} />
                    </Route>
                </Route>
            </Routes>
        </>
    )
}

export default AppRoutes