import React, { useState } from 'react';
import { X, Lock, Eye, EyeOff } from 'lucide-react';
import api, { authAPI } from '../../services/api';
import toast from 'react-hot-toast';
import { useAuth } from '../../context/AuthContext';

const ChangePasswordModal = ({ isOpen, onClose }) => {
    const { user,refreshUser } = useAuth();
    const [currentPassword, setCurrentPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [showCurrentPassword, setShowCurrentPassword] = useState(false);
    const [showNewPassword, setShowNewPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);
    const [loading, setLoading] = useState(false);

    // ✅ Check if user is OAuth-only (no existing password)
    const isOAuthOnly = user?.oauth_provider && !user?.hashed_password;

    const handleSubmit = async (e) => {
        e.preventDefault();

        // Validate new password
        if (newPassword.length < 8) {
            toast.error('Password must be at least 8 characters long');
            return;
        }

        const passwordPattern = /^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[@$!%*?#&])[A-Za-z\d@$!%*?#&]{8,}$/;
        if (!passwordPattern.test(newPassword)) {
            toast.error('Password must include uppercase, lowercase, number, and special character');
            return;
        }

        if (newPassword !== confirmPassword) {
            toast.error('New passwords do not match');
            return;
        }

        // ✅ For OAuth users setting password for the first time, no current password needed
        if (!isOAuthOnly && !currentPassword) {
            toast.error('Please enter your current password');
            return;
        }

        setLoading(true);

        try {
            if (isOAuthOnly) {
                // Setting password for the first time
                await authAPI.setPassword(newPassword);
                toast.success('Password set successfully! You can now login with email/password.');

                 // ✅ Refresh user data to show password is now set
                if (refreshUser) {
                    await refreshUser();
                }

            } else {
                // Changing existing password
                await authAPI.changePassword(currentPassword, newPassword);
                toast.success('Password changed successfully!');
            }


            onClose();
            setCurrentPassword('');
            setNewPassword('');
            setConfirmPassword('');
        } catch (error) {
            console.error('Password change failed:', error);
            toast.error(error.message || 'Failed to change password');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;


    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-xl shadow-2xl max-w-md w-full max-h-[90vh] overflow-y-auto">
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b border-gray-200">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-emerald-100 rounded-lg">
                            <Lock className="w-5 h-5 text-emerald-600" />
                        </div>
                        <h2 className="text-xl font-bold text-gray-900">
                            {isOAuthOnly ? 'Set Password' : 'Change Password'}
                        </h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-gray-400 hover:text-gray-600 transition-colors"
                    >
                        <X className="w-6 h-6" />
                    </button>
                </div>

                {/* Info Message for OAuth Users */}
                {isOAuthOnly && (
                    <div className="mx-6 mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                        <p className="text-sm text-blue-800">
                            <strong>Setting up backup login:</strong> You're currently logged in with {user.oauth_provider}.
                            Setting a password will allow you to log in with your email and password as well.
                        </p>
                    </div>
                )}

                {/* Form */}
                <form onSubmit={handleSubmit} className="p-6 space-y-5">
                    {/* Current Password - Only show if user has existing password */}
                    {!isOAuthOnly && (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Current Password
                            </label>
                            <div className="relative">
                                <input
                                    type={showCurrentPassword ? 'text' : 'password'}
                                    value={currentPassword}
                                    onChange={(e) => setCurrentPassword(e.target.value)}
                                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                                    placeholder="Enter current password"
                                    required
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                                >
                                    {showCurrentPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* New Password */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                            New Password
                        </label>
                        <div className="relative">
                            <input
                                type={showNewPassword ? 'text' : 'password'}
                                value={newPassword}
                                onChange={(e) => setNewPassword(e.target.value)}
                                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                                placeholder="Enter new password"
                                required
                            />
                            <button
                                type="button"
                                onClick={() => setShowNewPassword(!showNewPassword)}
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                            >
                                {showNewPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                            </button>
                        </div>
                    </div>

                    {/* Confirm Password */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                            Confirm New Password
                        </label>
                        <div className="relative">
                            <input
                                type={showConfirmPassword ? 'text' : 'password'}
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                                placeholder="Confirm new password"
                                required
                            />
                            <button
                                type="button"
                                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                            >
                                {showConfirmPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                            </button>
                        </div>
                    </div>

                    {/* Password Requirements */}
                    <div className="bg-gray-50 p-4 rounded-lg">
                        <p className="text-xs font-medium text-gray-700 mb-2">Password must contain:</p>
                        <ul className="text-xs text-gray-600 space-y-1">
                            <li className={newPassword.length >= 8 ? 'text-green-600' : ''}>
                                • At least 8 characters
                            </li>
                            <li className={/[A-Z]/.test(newPassword) && /[a-z]/.test(newPassword) ? 'text-green-600' : ''}>
                                • Uppercase and lowercase letters
                            </li>
                            <li className={/\d/.test(newPassword) ? 'text-green-600' : ''}>
                                • At least one number
                            </li>
                            <li className={/[@$!%*?#&]/.test(newPassword) ? 'text-green-600' : ''}>
                                • At least one special character (@$!%*?#&)
                            </li>
                        </ul>
                    </div>

                    {/* Buttons */}
                    <div className="flex gap-3 pt-4">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={loading}
                            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors disabled:opacity-50"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={loading}
                            className="flex-1 px-4 py-2 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50"
                        >
                            {loading ? 'Saving...' : isOAuthOnly ? 'Set Password' : 'Update Password'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ChangePasswordModal;

// // This creates a beautiful password change modal with:

// // ✅ Real-time password validation
// // ✅ Show/hide password toggles
// // ✅ Visual requirement indicators
// // ✅ Password match confirmation
// // ✅ Error handling
// // ✅ Loading states
