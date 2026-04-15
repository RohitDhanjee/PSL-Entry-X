// src/components/Logout.jsx
import { Button } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx'; // Adjust path as needed

const LogoutButton = () => {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <Button 
      variant="contained" 
      color="error"
      onClick={handleLogout}
      className="!bg-red-600 hover:!bg-red-700 !text-white"
    >
      Logout
    </Button>
  );
};

export default LogoutButton;
