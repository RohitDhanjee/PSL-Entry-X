// LogoutButton.jsx
import { useContext } from "react";
import { AuthContext } from "../context/AuthContext.jsx";
import { Button } from "antd";

const LogoutButton = () => {
  const { isLogin, logout } = useContext(AuthContext);

  if (!isLogin) return null; // agar login nahi hai tu button mat dikhana

  return (
    <Button type="primary" danger onClick={logout}>
      Logout
    </Button>
  );
};

export default LogoutButton;
