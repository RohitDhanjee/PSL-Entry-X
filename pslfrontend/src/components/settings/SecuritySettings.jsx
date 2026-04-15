import React, { useState, useEffect } from 'react';
import { Shield, Lock, Smartphone, Key, AlertCircle, CheckCircle } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { authAPI } from '../../services/api';
import toast from 'react-hot-toast';
import ChangePasswordModal from './ChangePasswordModal';
import TwoFactorAuth from './TwoFactorAuth';

const SecuritySettings = () => {
    console.log('🔄 SecuritySettings component rendered');

    const { user, refresh2FAStatus, refreshUser } = useAuth();
    const [is2FAEnabled, setIs2FAEnabled] = useState(false);
    const [loading, setLoading] = useState(true);
    const [showPasswordModal, setShowPasswordModal] = useState(false);
    const [show2FAModal, setShow2FAModal] = useState(false);

    console.log('📊 Current State:', {
        is2FAEnabled,
        loading,
        showPasswordModal,
        show2FAModal,
        user
    });

    // Check 2FA status on component mount
    useEffect(() => {
        check2FAStatus();
    }, []);

    const check2FAStatus = async () => {
        setLoading(true);
        try {
            const token = localStorage.getItem('token');
            console.log('🔍 Checking 2FA status with token:', !!token);

            if (!token) {
                console.log('❌ No token found, user not authenticated');
                setIs2FAEnabled(false);
                setLoading(false);
                return;
            }

            const response = await authAPI.get2FAStatus();
            const enabled = response.enabled || false;
            setIs2FAEnabled(enabled);
            console.log('✅ 2FA Status:', enabled);
        } catch (error) {
            console.error('Failed to check 2FA status:', error);

            // If 401, user is not authenticated
            if (error.response?.status === 401) {
                console.log('❌ Authentication failed');
                setIs2FAEnabled(false);
            }
        } finally {
            setLoading(false);
        }
    };

    const handle2FAToggle = () => {
        console.log('🔘 2FA Toggle clicked!');
        console.log('Current 2FA status:', is2FAEnabled);

        // Show modal for both enable and disable
        setShow2FAModal(true);
        console.log('Modal state set to: true');
    };

    // ✅ UPDATED: Handle 2FA status change with refresh
    const on2FAStatusChange = async (enabled) => {
        console.log('🔄 2FA status changed to:', enabled);
        setIs2FAEnabled(enabled);
        setShow2FAModal(false);

        // ✅ Refresh 2FA status in AuthContext
        if (refresh2FAStatus) {
            await refresh2FAStatus();
        }

        // ✅ Show success message
        if (enabled) {
            toast.success('Two-factor authentication enabled successfully!');
        } else {
            toast.success('Two-factor authentication disabled successfully!');
        }

        // ✅ Refresh status from server to ensure consistency
        await check2FAStatus();
    };

    // ✅ NEW: Close modal and refresh user data
    const handlePasswordModalClose = async () => {
        setShowPasswordModal(false);

        // Refresh user data to get updated hashed_password status
        if (refreshUser) {
            await refreshUser();
        }
    };


    return (
        <div className="max-w-4xl mx-auto p-6">
            {/* Header */}
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
                    <Shield className="w-8 h-8 text-emerald-600" />
                    Security Settings
                </h1>
                <p className="text-gray-600 mt-2">
                    Manage your account security and authentication methods
                </p>
            </div>

            {/* Security Cards */}
            <div className="space-y-6">

                {/* Two-Factor Authentication Card */}
                <div className="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden">
                    <div className="p-6">
                        <div className="flex items-start justify-between">
                            <div className="flex items-start gap-4">
                                <div className={`p-3 rounded-lg ${is2FAEnabled ? 'bg-green-100' : 'bg-gray-100'}`}>
                                    <Smartphone className={`w-6 h-6 ${is2FAEnabled ? 'text-green-600' : 'text-gray-600'}`} />
                                </div>
                                <div className="flex-1">
                                    <h3 className="text-lg font-semibold text-gray-900 mb-1">
                                        Two-Factor Authentication
                                    </h3>
                                    <p className="text-sm text-gray-600 mb-3">
                                        Add an extra layer of security to your account by requiring a verification code
                                    </p>

                                    {/* Status Badge */}
                                    {loading ? (
                                        <div className="flex items-center gap-2 text-sm">
                                            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-emerald-600"></div>
                                            <span className="text-gray-500">Checking status...</span>
                                        </div>
                                    ) : (
                                        <div className="flex items-center gap-2">
                                            {is2FAEnabled ? (
                                                <>
                                                    <CheckCircle className="w-4 h-4 text-green-600" />
                                                    <span className="text-sm font-medium text-green-600">
                                                        Enabled
                                                    </span>
                                                </>
                                            ) : (
                                                <>
                                                    <AlertCircle className="w-4 h-4 text-yellow-600" />
                                                    <span className="text-sm font-medium text-yellow-600">
                                                        Disabled
                                                    </span>
                                                </>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>

                            <button
                                onClick={handle2FAToggle}
                                disabled={loading}
                                className={`px-4 py-2 rounded-lg font-medium transition-all ${is2FAEnabled
                                    ? 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200'
                                    : 'bg-emerald-600 text-white hover:bg-emerald-700'
                                    } disabled:opacity-50 disabled:cursor-not-allowed`}
                            >
                                <span style={{ color: 'white' }}>
                                    {is2FAEnabled ? 'Disable 2FA' : 'Enable 2FA'}
                                </span>
                            </button>
                        </div>

                        {/* Info Box */}
                        {!is2FAEnabled && (
                            <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                                <div className="flex gap-3">
                                    <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                                    <div className="text-sm text-blue-800">
                                        <p className="font-medium mb-1">Why enable 2FA?</p>
                                        <ul className="list-disc list-inside space-y-1 text-blue-700">
                                            <li>Protects your account even if your password is compromised</li>
                                            <li>Uses authenticator apps like Google Authenticator or Authy</li>
                                            <li>Recommended for all users, especially artists and collectors</li>
                                        </ul>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* ✅ NEW: Success message when 2FA is enabled */}
                        {is2FAEnabled && (
                            <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
                                <div className="flex gap-3">
                                    <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                                    <div className="text-sm text-green-800">
                                        <p className="font-medium mb-1">Two-Factor Authentication is Active</p>
                                        <p className="text-green-700">
                                            Your account is protected. You'll need to enter a code from your authenticator app each time you log in.
                                        </p>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Change Password Card */}
                <div className="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden">
                    <div className="p-6">
                        <div className="flex items-start justify-between">
                            <div className="flex items-start gap-4">
                                <div className="p-3 bg-emerald-100 rounded-lg">
                                    <Lock className="w-6 h-6 text-emerald-600" />
                                </div>
                                <div className="flex-1">
                                    <h3 className="text-lg font-semibold text-gray-900 mb-1">
                                        <span style={{ color: 'Black' }}>
                                            {user?.oauth_provider && !user?.hashed_password
                                                ? 'Set Password (Optional)'
                                                : 'Change Password'
                                            }
                                        </span>
                                    </h3>

                                    {/* ✅ Different messages based on auth method */}
                                    {user?.oauth_provider && !user?.hashed_password ? (
                                        <>
                                            <p className="text-sm text-gray-600">
                                                You're currently signed in with {user.oauth_provider}.
                                                You can optionally set a password to enable email/password login.
                                            </p>
                                            <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                                                <p className="text-xs text-blue-800">
                                                    <strong>Why set a password?</strong> Having a password as backup
                                                    allows you to log in even if you can't access your Google account.
                                                </p>
                                            </div>
                                        </>
                                    ) : user?.oauth_provider ? (
                                        <>
                                            <p className="text-sm text-gray-600">
                                                Update your password regularly to keep your account secure.
                                                You can still log in with {user.oauth_provider}.
                                            </p>
                                            {/* ✅ NEW: Show that user has both login methods */}
                                            <div className="flex items-center gap-2 text-xs mt-2">
                                                <span className="px-2 py-1 bg-green-50 text-green-700 rounded-full border border-green-200">
                                                    ✓ Email/Password
                                                </span>
                                                <span className="px-2 py-1 bg-blue-50 text-blue-700 rounded-full border border-blue-200">
                                                    ✓ Google OAuth
                                                </span>
                                            </div>
                                        </>
                                    ) : (
                                        <p className="text-sm text-gray-600">
                                            Update your password regularly to keep your account secure
                                        </p>
                                    )}
                                </div>
                            </div>

                            <button
                                onClick={() => setShowPasswordModal(true)}
                                className="px-4 py-2 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-all"
                            >
                                <span style={{ color: 'white' }}>
                                    {user?.oauth_provider && !user?.hashed_password
                                        ? 'Set Password'
                                        : 'Update Password'
                                    }
                                </span>
                            </button>
                        </div>


                        {/* Password Requirements */}
                        <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
                            <p className="text-sm font-medium text-gray-700 mb-2">Password Requirements:</p>
                            <ul className="text-xs text-gray-600 space-y-1">
                                <li>• At least 8 characters long</li>
                                <li>• Include uppercase and lowercase letters</li>
                                <li>• Include at least one number</li>
                                <li>• Include at least one special character (@$!%*?#&)</li>
                            </ul>
                        </div>
                    </div>
                </div>

                {/* Connected Accounts Card */}
                <div className="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden">
                    <div className="p-6">
                        <div className="flex items-start gap-4">
                            <div className="p-3 bg-blue-100 rounded-lg">
                                <Key className="w-6 h-6 text-blue-600" />
                            </div>
                            <div className="flex-1">
                                <h3 className="text-lg font-semibold text-gray-900 mb-1">
                                    Connected Accounts
                                </h3>
                                <p className="text-sm text-gray-600 mb-4">
                                    Manage your linked authentication providers
                                </p>

                                {/* Connected Providers */}
                                <div className="space-y-3">
                                    {/* Email/Password */}
                                    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                                        <div className="flex items-center gap-3">
                                            <div className="w-8 h-8 bg-emerald-100 rounded-full flex items-center justify-center">
                                                <Lock className="w-4 h-4 text-emerald-600" />
                                            </div>
                                            <div>
                                                <p className="text-sm font-medium text-gray-900">Email & Password</p>
                                                <p className="text-xs text-gray-500">{user?.email}</p>
                                            </div>
                                        </div>
                                        <span className="text-xs text-green-600 font-medium">Active</span>
                                    </div>

                                    {/* Google OAuth */}
                                    {user?.oauth_provider === 'google' && (
                                        <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                                            <div className="flex items-center gap-3">
                                                <svg className="w-8 h-8" viewBox="0 0 24 24">
                                                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                                                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                                                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                                                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                                                </svg>
                                                <div>
                                                    <p className="text-sm font-medium text-gray-900">Google</p>
                                                    <p className="text-xs text-gray-500">OAuth connected</p>
                                                </div>
                                            </div>
                                            <span className="text-xs text-green-600 font-medium">Connected</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

            </div>

            {/* Modals */}
            {
                showPasswordModal && (
                    <ChangePasswordModal
                        isOpen={showPasswordModal}
                        onClose={handlePasswordModalClose} // ✅ CHANGED: Use new handler
                    />
                )
            }

            {
                show2FAModal && (
                    <TwoFactorAuth
                        isOpen={show2FAModal}
                        onClose={() => setShow2FAModal(false)}
                        isEnabled={is2FAEnabled}
                        onStatusChange={on2FAStatusChange}
                    />
                )
            }
        </div >
    );
};

export default SecuritySettings;

// // This creates the main security dashboard with:

// // ✅ 2FA enable/disable toggle
// // ✅ Change password button
// // ✅ Connected accounts display
// // ✅ Status indicators
