import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { yupResolver } from "@hookform/resolvers/yup";
import * as yup from "yup";
import {
  Upload,
  X,
  AlertCircle,
  Palette,
  Shield,
  CheckCircle,
  XCircle,
  Eye,
  Database,
  Zap,
  Copy,
  AlertTriangle,
  Image as ImageIcon,
  CreditCard,
  Wallet,
  Ticket,
  MapPin,
  Calendar,
  Clock,
  Armchair,
} from "lucide-react";
import {
  Button,
  Input,
  InputLabel,
  CircularProgress,
  Box,
  Typography,
  MenuItem,
  Switch,
  FormControl,
  Select,
} from "@mui/material";
import { useWeb3 } from "../../../context/Web3Context";
import { useAuth } from "../../../context/AuthContext";
import { ticketsAPI } from "../../../services/api";
import { cacheService } from "../../../services/cacheService";
import { CurrencyConverter } from "../../../utils/currencyUtils";
import LoadingSpinner from "../../../components/common/LoadingSpinner";
import toast from "react-hot-toast";
import imageCompression from "browser-image-compression";
import { useSettings } from "../../../context/SettingsContext";

// REMOVED: schema is now inside the component to handle dynamic PSL validation

const dataURLtoFile = (dataurl, filename) => {
  if (!dataurl) return null;
  try {
    const arr = dataurl.split(',');
    const mime = arr[0].match(/:(.*?);/)[1];
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    return new File([u8arr], filename, { type: mime });
  } catch (e) {
    console.error("Error restoring file:", e);
    return null;
  }
};

const UploadTickets = () => {
  const navigate = useNavigate();
  const { enableCrypto, loading: settingsLoading } = useSettings();
  const enablePayPal = false;

  const { 
    account, 
    sendTransaction, 
    isCorrectNetwork, 
    connectWallet, 
    switchNetwork, 
    selectedNetwork, 
    currencySymbol, 
    currentNetworkConfig 
  } = useWeb3();
  const { isWalletConnected } = useAuth();

  const loyaltyPercentage = [
    { id: 1, percentage: "5%", value: 500 },
    { id: 2, percentage: "10%", value: 1000 },
    { id: 3, percentage: "15%", value: 1500 },
    { id: 4, percentage: "20%", value: 2000 },
  ];

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [transactionHash, setTransactionHash] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [currentStep, setCurrentStep] = useState("upload");
  const [uploadedFile, setUploadedFile] = useState(null);
  const [priceInputMode, setPriceInputMode] = useState("eth"); // "eth" or "usd"

  // NEW: State for categories
  const [categories, setCategories] = useState({
    medium: [{ id: "loading", name: "Loading..." }],
    style: [{ id: "loading", name: "Loading..." }],
    subject: [{ id: "loading", name: "Loading..." }],
  });

  const [categoriesLoading, setCategoriesLoading] = useState({
    medium: true,
    style: true,
    subject: true,
  });

  const [showOtherMedium, setShowOtherMedium] = useState(false);
  const [showOtherStyle, setShowOtherStyle] = useState(false);
  const [showOtherSubject, setShowOtherSubject] = useState(false);

  // Validation states
  const [duplicateCheck, setDuplicateCheck] = useState(null);
  const [aiClassification, setAiClassification] = useState(null);
  const [isChecking, setIsChecking] = useState(false);
  const [validationPassed, setValidationPassed] = useState(false);
  const [validationError, setValidationError] = useState(null);
  const [existingTicketDetails, setExistingTicketDetails] = useState(null);
  const [registrationMethod, setRegistrationMethod] = useState("on-chain"); // NEW: "on-chain" or "off-chain"
  const [responsibleUseAddon, setResponsibleUseAddon] = useState(false); // NEW: Addon state
  
  // PSL mode is always enabled for this flow.
  const isPSLTicket = true;
  const [pslMetadata, setPslMetadata] = useState({
    seat_number: "",
    stand: "",
    venue: "National Stadium, Karachi",
    match_date: "",
    match_time: "19:00"
  });

  // Automatically switch payment method based on what is enabled
  // ✅ Auto-select registration method based on available payment options
  useEffect(() => {
    if (!settingsLoading) {
      if (isPSLTicket) {
        setRegistrationMethod("on-chain");
        return;
      }

      setRegistrationMethod("on-chain");
    }
  }, [enableCrypto, settingsLoading, isPSLTicket]);
  
  // PSL Venue and Stand options
  const pslVenues = [
    "National Stadium, Karachi",
    "Gaddafi Stadium, Lahore",
    "Rawalpindi Cricket Stadium",
    "Multan Cricket Stadium",
    "Arbab Niaz Stadium, Peshawar"
  ];
  
  const pslStands = [
    "VIP Enclosure",
    "Premium Enclosure",
    "General Stand A",
    "General Stand B",
    "Family Stand",
    "Student Stand"
  ];
  
  // ✅ DYNAMIC VALIDATION SCHEMA
  const schema = React.useMemo(() => {
    return yup.object({
      title: yup.string().required("Title is required").max(100, "Title too long"),
      description: yup
        .string()
        .required("Description is required")
        .max(1000, "Description too long"),
      royalty_percentage: isPSLTicket 
        ? yup.number().notRequired()
        : yup.number()
            .required("Royalty percentage is required")
            .min(0, "Royalty cannot be negative")
            .max(2000, "Royalty cannot exceed 20% (2000 basis points)")
            .integer("Royalty must be a whole number"),
      price: yup
        .number()
        .required("Price is required")
        .min(0, "Price cannot be negative"),
      medium_category: isPSLTicket ? yup.string().notRequired() : yup.string().required("Medium category is required"),
      style_category: isPSLTicket ? yup.string().notRequired() : yup.string().required("Style category is required"),
      subject_category: isPSLTicket ? yup.string().notRequired() : yup.string().required("Subject category is required"),
      image: yup
        .mixed()
        .required("Image is required")
        .test("fileSize", "File too large (max 10MB)", (value) => {
          if (!value) return false;
          return value.size <= 10 * 1024 * 1024; // 10MB limit
        })
        .test("fileType", "Unsupported file type", (value) => {
          if (!value) return false;
          return ["image/jpeg", "image/png", "image/gif", "image/webp"].includes(
            value.type
          );
        }),
    });
  }, [isPSLTicket]);

  // ✅ NEW: Ref for auto-scroll
  const addonRef = useRef(null);

  // ✅ NEW: Auto-scroll effect - when enabled OR when validation passed and we land on this step
  useEffect(() => {
    if (responsibleUseAddon && addonRef.current) {
      setTimeout(() => {
        addonRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
    }
  }, [responsibleUseAddon]);

  const {
    register,
    handleSubmit,
    formState: { errors },
    watch,
    reset,
    setValue,
  } = useForm({
    resolver: yupResolver(schema),
    defaultValues: {
      royalty_percentage: 1000,
      price: "",
      medium_category: "",
      style_category: "",
      subject_category: "",
      other_medium: "",
      other_style: "",
      other_subject: "",
      image: null,
      description: "", // ✅ Ensure this is empty, not "Hand-painted ticket"
    },
  });
  // ✅ RESTORE DRAFT: Runs once on page load
  useEffect(() => {
    const savedDraft = localStorage.getItem('ticket_upload_draft');

    if (savedDraft) {
      try {
        console.log("Found saved draft, restoring...");
        const parsed = JSON.parse(savedDraft);

        // 1. Restore Price Mode FIRST (so the unit is correct)
        if (parsed.priceInputMode) {
          setPriceInputMode(parsed.priceInputMode);
        }

        // 2. Restore Text Fields
        setValue('title', parsed.title || '');
        setValue('description', parsed.description || '');

        // FIX: Check if price is not null/undefined so 0 is preserved
        const savedPrice = (parsed.price !== undefined && parsed.price !== null) ? parsed.price : '';
        setValue('price', savedPrice);

        setValue('royalty_percentage', parsed.royalty_percentage || 1000);
        setValue('medium_category', parsed.medium_category || '');
        setValue('style_category', parsed.style_category || '');
        setValue('subject_category', parsed.subject_category || '');

        // 3. Restore Image & Preview
        if (parsed.imageBase64 && parsed.fileName) {
          const file = dataURLtoFile(parsed.imageBase64, parsed.fileName);
          if (file) {
            setUploadedFile(file);
            setValue('image', file, { shouldValidate: true });
            setPreviewUrl(parsed.imageBase64);
          }
        }

        // 4. Restore Validation States
        if (parsed.validationPassed) {
          setDuplicateCheck(parsed.duplicateCheck);
          setAiClassification(parsed.aiClassification);
          setValidationPassed(true);
          toast.success("Resumed previous upload session");
        }

      } catch (error) {
        console.error("Failed to restore draft:", error);
        localStorage.removeItem('ticket_upload_draft');
      }
    }
  }, []);

  // ✅ Clear draft when registration is complete
  useEffect(() => {
    if (currentStep === "complete") {
      localStorage.removeItem('artwork_upload_draft');
    }
  }, [currentStep]);

  // ✅ AUTO-SAVE: Runs whenever important data changes
  useEffect(() => {
    // Don't save draft if we're on the complete step (registration finished)
    if (currentStep === "complete") {
      return;
    }

    // Only save if there is at least a title or a file
    const currentValues = watch(); // Get all form values

    if (currentValues.title || uploadedFile) {
      const draftData = {
        // Form Values
        title: currentValues.title,
        description: currentValues.description,
        price: currentValues.price,
        priceInputMode: priceInputMode, // <--- ADD THIS LINE (Saves ETH vs USD choice)
        royalty_percentage: currentValues.royalty_percentage,
        medium_category: currentValues.medium_category,
        style_category: currentValues.style_category,
        subject_category: currentValues.subject_category,

        // Image Data
        imageBase64: previewUrl,
        fileName: uploadedFile ? uploadedFile.name : null,

        // Check Results
        duplicateCheck: duplicateCheck,
        aiClassification: aiClassification,
        validationPassed: validationPassed
      };

      try {
        localStorage.setItem('ticket_upload_draft', JSON.stringify(draftData));
      } catch (e) {
        // Handle "Quota Exceeded" if image is too massive
        console.warn("Draft too large to save automatically");
      }
    }
  }, [
    currentStep,
    watch('title'),
    watch('description'),
    watch('price'),
    priceInputMode,
    uploadedFile,
    previewUrl,
    duplicateCheck,
    aiClassification,
    validationPassed
  ]);

  const image = watch("image");
  const mediumCategory = watch("medium_category");
  const styleCategory = watch("style_category");
  const subjectCategory = watch("subject_category");
  const priceValue = watch("price");

  // Load categories on component mount
  useEffect(() => {
    const loadCategories = async () => {
      try {
        setCategoriesLoading({ medium: true, style: true, subject: true });

        const responses = await Promise.allSettled([
          ticketsAPI.getCategories("medium"),
          ticketsAPI.getCategories("style"),
          ticketsAPI.getCategories("subject"),
        ]);

        console.log("Category API responses:", responses);

        const extractData = (result, type) => {
          if (result.status === "rejected") {
            console.error(`${type} categories failed:`, result.reason);
            return [{ id: "error", name: `Error loading ${type}` }];
          }

          const response = result.value;

          // Try different response structures
          if (Array.isArray(response)) return response;
          if (response?.data && Array.isArray(response.data))
            return response.data;
          if (response?.categories && Array.isArray(response.categories))
            return response.categories;

          console.warn(`Unexpected ${type} response:`, response);
          return [{ id: "empty", name: `No ${type} found` }];
        };

        setCategories({
          medium: extractData(responses[0], "medium"),
          style: extractData(responses[1], "style"),
          subject: extractData(responses[2], "subject"),
        });

        setCategoriesLoading({ medium: false, style: false, subject: false });
      } catch (error) {
        console.error("Categories loading failed:", error);

        // Fallback categories
        setCategories({
          medium: [{ id: "other", name: "Other Medium" }],
          style: [{ id: "other", name: "Other Style" }],
          subject: [{ id: "other", name: "Other Subject" }],
        });

        setCategoriesLoading({ medium: false, style: false, subject: false });
      }
    };

    loadCategories();
  }, []);

  // Show/hide other fields based on category selection
  useEffect(() => {
    setShowOtherMedium(mediumCategory === "Other Medium");
  }, [mediumCategory]);

  useEffect(() => {
    setShowOtherStyle(styleCategory === "Other Style");
  }, [styleCategory]);

  useEffect(() => {
    setShowOtherSubject(subjectCategory === "Other Subject");
  }, [subjectCategory]);

  // Handle price input mode changes - FIXED: Only convert when mode changes, not on every render
  useEffect(() => {
    // Only convert if we have a valid price value AND the mode actually changed
    const currentPrice = watch("price");
    if (currentPrice && !isNaN(currentPrice) && currentPrice !== "" && currentPrice !== 0) {
      // Only convert when switching modes, preserve the value otherwise
      // This effect should only run when priceInputMode changes, not when price changes
    }
  }, [priceInputMode]); // ✅ FIXED: Only depend on priceInputMode, not priceValue

  // Generate preview when image changes
  useEffect(() => {
    if (image && image instanceof File) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setPreviewUrl(reader.result);
      };
      reader.readAsDataURL(image);
    } else {
      setPreviewUrl(null);
    }
  }, [image, validationPassed]);

  const compressImage = async (file) => {
    const options = {
      maxSizeMB: 5, // Maximum file size in MB
      maxWidthOrHeight: 2000, // Maximum width or height
      useWebWorker: true,
      fileType: "image/jpeg", // Convert to JPEG for better compression
    };

    try {
      const compressedFile = await imageCompression(file, options);
      return compressedFile;
    } catch (error) {
      console.error("Image compression failed:", error);
      throw new Error("Failed to compress image");
    }
  };

  // Direct upload readiness (AI/duplicate checks removed)
  const performValidationChecks = async (file) => {
    if (!file) return;

    setIsChecking(false);
    setDuplicateCheck(null);
    setAiClassification(null);
    setValidationError(null);
    setExistingTicketDetails(null);

    setValidationPassed(true);
    const reader = new FileReader();
    reader.onloadend = () => {
      setPreviewUrl(reader.result);
    };
    reader.readAsDataURL(file);
    toast.success("Ticket file uploaded. Continue to details.");
  };

  // Enhanced submit function with categories and price
  const onSubmit = async (data) => {
    console.log("Form submitted with data:", data);
    console.log("Registration method:", registrationMethod);

    if (isPSLTicket && registrationMethod !== "on-chain") {
      toast.error("PSL Smart-Tickets can only be registered on-chain.", { duration: 5000 });
      return;
    }

    // ✅ ENHANCED: Validate all required fields before proceeding
    const requiredFields = {
      title: data.title,
      description: data.description,
      price: data.price,
      royalty_percentage: isPSLTicket ? "0" : data.royalty_percentage,
      medium_category: isPSLTicket ? "PSL_TICKET" : data.medium_category,
      style_category: isPSLTicket ? "PSL_TICKET" : data.style_category,
      subject_category: isPSLTicket ? "PSL_TICKET" : data.subject_category,
      image: data.image || uploadedFile,
    };

    // Check if any required field is missing or empty
    const missingFields = [];
    if (!requiredFields.title || requiredFields.title.trim() === "") {
      missingFields.push("Title");
    }
    if (!requiredFields.description || requiredFields.description.trim() === "") {
      missingFields.push("Description");
    }
    if (!requiredFields.price || requiredFields.price === "" || isNaN(requiredFields.price) || parseFloat(requiredFields.price) <= 0) {
      missingFields.push("Price (must be greater than 0)");
    }
    
    // Only validate ticket categories if NOT a PSL ticket
    if (!isPSLTicket) {
      if (!requiredFields.medium_category || requiredFields.medium_category === "") {
        missingFields.push("Medium Category");
      }
      if (!requiredFields.style_category || requiredFields.style_category === "") {
        missingFields.push("Style Category");
      }
      if (!requiredFields.subject_category || requiredFields.subject_category === "") {
        missingFields.push("Subject Category");
      }
    }

    if (!requiredFields.image) {
      missingFields.push("Image");
    }

    if (isPSLTicket) {
      if (!pslMetadata.seat_number?.trim()) {
        missingFields.push("Seat Number");
      }
      if (!pslMetadata.stand?.trim()) {
        missingFields.push("Stand/Section");
      }
      if (!pslMetadata.venue?.trim()) {
        missingFields.push("Venue");
      }
      if (!pslMetadata.match_date?.trim()) {
        missingFields.push("Match Date");
      }
      if (!pslMetadata.match_time?.trim()) {
        missingFields.push("Match Time");
      }
    }

    if (missingFields.length > 0) {
      toast.error(`Please fill all required fields: ${missingFields.join(", ")}`, { duration: 5000 });
      return;
    }

    // ✅ Check requirements based on registration method and provide helpful guidance
    if (registrationMethod === "on-chain") {
      if (!account) {
        toast.error(
          "Wallet not connected. Please connect your MetaMask wallet to register on-chain.",
          { duration: 5000 }
        );

        // Try to connect automatically
        const connected = await connectWallet();
        if (!connected) return;
      }

      if (!isCorrectNetwork) {
        toast.error(
          `Please switch to ${currentNetworkConfig.label} to register on-chain.`,
          { duration: 5000 }
        );
        const switched = await switchNetwork(selectedNetwork);
        if (!switched) return;
      }
    } else if (registrationMethod === "off-chain") {
      toast.error("Off-chain registration is no longer supported. Please use on-chain registration.", { duration: 5000 });
      return;
    }

    if (!uploadedFile) {
      toast.error("No image file found. Please upload an image first.");
      return;
    }

    setIsSubmitting(true);

    try {
      // Compress image before upload
      const compressedImage = await compressImage(data.image);

      // Convert price to ETH if input was in USD
      let finalPrice = data.price;
      if (priceInputMode === "usd") {
        finalPrice = CurrencyConverter.usdToEth(data.price);
      }

      // Create FormData with compressed image, categories, and price
      const formData = new FormData();
      const effectiveRegistrationMethod = isPSLTicket ? "on-chain" : registrationMethod;
      formData.append("title", data.title);
      formData.append("description", data.description || "");
      formData.append("registration_method", effectiveRegistrationMethod); // PSL tickets are on-chain only
      formData.append("royalty_percentage", isPSLTicket ? "0" : data.royalty_percentage.toString());
      formData.append("price", finalPrice.toString());
      formData.append("medium_category", isPSLTicket ? "PSL_SMART_TICKET" : data.medium_category);
      formData.append("style_category", isPSLTicket ? "PSL_SMART_TICKET" : data.style_category);
      formData.append("subject_category", isPSLTicket ? "PSL_SMART_TICKET" : data.subject_category);
      formData.append("responsible_use_addon", isPSLTicket ? "false" : responsibleUseAddon.toString());
      formData.append("network", currentNetworkConfig.shortLabel.toLowerCase()); // ✅ ADDED NETWORK
      formData.append("image", compressedImage, data.image.name);

      // Add other category fields if they exist
      if (!isPSLTicket) {
        if (data.other_medium) {
          formData.append("other_medium", data.other_medium);
        }
        if (data.other_style) {
          formData.append("other_style", data.other_style);
        }
        if (data.other_subject) {
          formData.append("other_subject", data.other_subject);
        }
      }
      
      // Explicitly add network to registration
      formData.append("network", selectedNetwork || "wirefluid");
      
      // PSL Smart-Ticket metadata (Hackathon Demo)
      if (isPSLTicket) {
        formData.append("is_psl_ticket", "true");
        formData.append("psl_seat_number", pslMetadata.seat_number);
        formData.append("psl_stand", pslMetadata.stand);
        formData.append("psl_venue", pslMetadata.venue);
        formData.append("psl_match_date", pslMetadata.match_date);
        formData.append("psl_match_time", pslMetadata.match_time);
      }

      // Phase 1: Register with enhanced validation
      const prepToast = toast.loading("Processing and registering ticket...");

      let preparation;
      try {
        preparation = await ticketsAPI.registerWithImage(formData);
      } catch (error) {
        toast.dismiss(prepToast);

        // ✅ Check for PayPal onboarding error
        if (
          error.message.includes("onboarding required") ||
          error.message.includes("onboarding") ||
          error.response?.data?.detail?.includes("onboarding")
        ) {
          throw new Error(
            "PayPal seller onboarding required. Please complete PayPal onboarding in Settings before registering tickets."
          );
        } else if (
          error.message.includes("timeout") ||
          error.message.includes("timed out")
        ) {
          throw new Error(
            "Upload timed out. Please try with a smaller image or try again later."
          );
        } else if (error.message.includes("404")) {
          throw new Error(
            "Server endpoint not found. Please check if the server is running correctly."
          );
        } else if (error.message.includes("Registration endpoint not found")) {
          throw new Error(
            "Server configuration error. Please contact support."
          );
        } else {
          // ✅ Show the actual error message from backend
          const errorMessage = error.response?.data?.detail || error.message || "Registration failed";
          throw new Error(errorMessage);
        }
      }

      toast.dismiss(prepToast);

      // Check for rejection responses
      if (preparation.status === "rejected") {
        if (preparation.reason === "duplicate") {
          throw new Error(`Duplicate detected: ${preparation.message}`);
        } else if (preparation.reason === "ai_generated") {
          throw new Error(`AI-generated content: ${preparation.message}`);
        } else {
          throw new Error(`Upload rejected: ${preparation.message}`);
        }
      }

      // Off-chain registration has been removed.
      const regMethod = preparation.registration_method || preparation.payment_method; // Backward compatibility
      if (regMethod === "off-chain" || regMethod === "paypal") {
        throw new Error("Off-chain/PayPal registration is no longer supported.");
      }

      // Handle on-chain registration (MetaMask flow) - NEW: Check registration_method first
      if (regMethod === "on-chain" || regMethod === "crypto") {
        if (!preparation.transaction_data) {
          throw new Error("Backend did not return transaction data");
        }

        setCurrentStep("blockchain");

        // Phase 2: Send blockchain transaction
        const txToast = toast.loading("Sending transaction...");

        const txResponse = await sendTransaction({
          ...preparation.transaction_data,
          from: account,
          gas: 500000,
        });
        toast.dismiss(txToast);

        // Phase 3: Confirm registration (include categories and price)
        const finalizingToast = toast.loading("Finalizing registration...");
        try {
          const confirmation = await ticketsAPI.confirmRegistration({
            tx_hash: txResponse.hash,
            from_address: account,
            metadata_uri: preparation.metadata_uri,
            image_uri: preparation.image_uri,
            image_metadata: preparation.image_metadata,
            royalty_percentage: data.royalty_percentage,
            price: finalPrice,
            title: data.title,
            description: data.description,
            network: selectedNetwork || "wirefluid",
            categories: {
              medium: data.medium_category,
              style: isPSLTicket ? "PSL_SMART_TICKET" : data.style_category,
              subject: isPSLTicket ? "PSL_SMART_TICKET" : data.subject_category,
              other_medium: data.other_medium || null,
              other_style: data.other_style || null,
              other_subject: data.other_subject || null,
            },
            registration_method: preparation.registration_method || "on-chain",
            // PSL Smart-Ticket data (Hackathon Demo)
            is_psl_ticket: isPSLTicket,
            psl_metadata: isPSLTicket ? pslMetadata : null
          });

          if (!confirmation.success) {
            console.warn("Registration confirmation had issues:", confirmation);
          }

          toast.dismiss(finalizingToast);
        } catch (confirmError) {
          console.warn(
            "Registration confirmation failed, but transaction was successful:",
            confirmError
          );
          toast.dismiss(finalizingToast);
        }

        toast.success(`${isPSLTicket ? "Ticket" : "Ticket"} registered successfully!`);
        
        // ✅ NEW: Invalidate all caches after successful registration
        cacheService.invalidateAll();
        
        reset();
        setCurrentStep("complete");
      }
    } catch (error) {
      toast.dismiss();
      console.error("Registration error:", error);

      if (error.message.includes("Duplicate detected")) {
        toast.error(
          "Duplicate image detected. Please choose a different image."
        );
      } else if (error.message.includes("AI-generated content")) {
        toast.error(
          "AI-generated content is not allowed. Please upload original ticket."
        );
      } else if (
        error.message.includes("timeout") ||
        error.message.includes("timed out")
      ) {
        toast.error(
          "Upload timed out. Please try with a smaller image or check your internet connection."
        );
      } else if (
        error.message.includes("404") ||
        error.message.includes("not found")
      ) {
        toast.error(
          "Server configuration error. Please ensure the backend server is running correctly."
        );
      } else {
        toast.error(`Upload failed: ${error.message}`);
      }

      setCurrentStep("details");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileChange = async (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setUploadedFile(file);
      setValue("image", file, { shouldValidate: true });

      // Automatically perform validation checks
      await performValidationChecks(file);
    }
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      setUploadedFile(file);
      setValue("image", file, { shouldValidate: true });

      // Automatically perform validation checks
      await performValidationChecks(file);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  const handleRemoveFile = () => {
    setUploadedFile(null);
    setPreviewUrl(null);
    setValue("image", null);
    setDuplicateCheck(null);
    setAiClassification(null);
    setValidationPassed(false);
    setValidationError(null);
    setExistingTicketDetails(null);
  };

  const handleRetryValidation = () => {
    if (uploadedFile) {
      performValidationChecks(uploadedFile);
    }
  };

  const handleUpload = async () => {
    if (uploadedFile) {
      if (!watch("image")) {
        setValue("image", uploadedFile, { shouldValidate: false });
      }
      setCurrentStep("details");
    } else {
      toast.error("Please upload an image first");
    }
  };

  // Format price display
  const formatPriceDisplay = () => {
    if (!priceValue || isNaN(priceValue)) return "Enter price";

    if (priceInputMode === "usd") {
      return CurrencyConverter.formatUsd(priceValue);
    }
    return CurrencyConverter.formatCrypto(priceValue, selectedNetwork);
  };

  // Validation status component
  const ValidationStatus = ({ check, title, type }) => {
    if (!check && !isChecking) return null;

    const getStatusColor = () => {
      if (isChecking) return "text-blue-500";
      if (type === "duplicate" && check?.is_duplicate) return "text-red-500";
      if (type === "ai" && check?.is_ai_generated) return "text-red-500";
      return "text-green-500";
    };

    const getStatusIcon = () => {
      if (isChecking) return <CircularProgress size={16} />;
      if (type === "duplicate" && check?.is_duplicate)
        return <XCircle className="w-5 h-5" />;
      if (type === "ai" && check?.is_ai_generated)
        return <XCircle className="w-5 h-5" />;
      return <CheckCircle className="w-5 h-5" />;
    };

    const getStatusText = () => {
      if (isChecking) return "Checking...";
      if (type === "duplicate") {
        return check?.is_duplicate
          ? `Duplicate found: ${check.message}`
          : "No duplicates found";
      }
      if (type === "ai") {
        return check?.is_ai_generated
          ? `AI-generated: ${check.description} (${(
            check.confidence * 100
          ).toFixed(1)}% confidence)`
          : "Human-created content";
      }
      return "";
    };

    return (
      <div className={`flex items-center mt-2 text-sm ${getStatusColor()}`}>
        <span className="mr-2">{getStatusIcon()}</span>
        <span>
          <strong>{title}:</strong> {getStatusText()}
        </span>
      </div>
    );
  };

  // Component to show existing ticket details for duplicates
  const ExistingTicketDetails = ({ ticket }) => {
    if (!ticket) return null;

    return (
      <div className="mt-4 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
        <h4 className="font-medium text-yellow-800 mb-2">
          ⚠️ Similar Ticket Already Exists
        </h4>

        <div className="flex flex-col sm:flex-row gap-4">
          {ticket.image_uri && (
            <div className="w-32 h-32 flex-shrink-0">
              <img
                src={ticket.image_uri}
                alt="Existing ticket"
                className="w-full h-full object-cover rounded"
              />
            </div>
          )}

          <div className="flex-1">
            <h5 className="font-semibold text-gray-900">
              {ticket.title || "Untitled"}
            </h5>
            {ticket.description && (
              <p className="text-sm text-gray-600 mt-1">
                {ticket.description}
              </p>
            )}
            <div className="mt-2 text-xs text-gray-500">
              <p>
                Creator: {ticket.creator_address?.slice(0, 8)}...
                {ticket.creator_address?.slice(-6)}
              </p>
              <p>Token ID: {ticket.token_id}</p>
              {ticket.created_at && (
                <p>
                  Created: {new Date(ticket.created_at).toLocaleDateString()}
                </p>
              )}
            </div>
          </div>
        </div>

        <p className="mt-3 text-sm text-yellow-700">
          Please upload a different, original ticket to avoid duplication.
        </p>
      </div>
    );
  };

  // Component to show validation error instead of preview
  const ValidationErrorDisplay = ({
    error,
    duplicateCheck,
    existingTicket,
  }) => {
    if (!error) return null;

    return (
      <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
        <div className="flex items-center text-red-800 mb-2">
          <AlertCircle className="w-5 h-5 mr-2" />
          <h4 className="font-medium">Upload Rejected</h4>
        </div>
        <p className="text-red-700">{error}</p>
        {duplicateCheck?.is_duplicate && (
          <div className="mt-3">
            <p className="text-sm text-red-600">
              <strong>Similarity Score:</strong>{" "}
              {duplicateCheck.similarity_score
                ? `${(duplicateCheck.similarity_score * 100).toFixed(1)}%`
                : "High similarity detected"}
            </p>
            <p className="text-sm text-red-600">
              <strong>Detection Type:</strong> {duplicateCheck.duplicate_type}
            </p>
          </div>
        )}
        ;
        {existingTicket && (
          <ExistingTicketDetails ticket={existingTicket} />
        )}
        <div className="mt-3 p-3 bg-red-100 rounded">
          <p className="text-xs text-red-600">
            <strong>Note:</strong> Uploading duplicate or AI-generated content
            violates our platform policies. Please ensure your {isPSLTicket ? "item" : "ticket"} is
            original and created by you.
          </p>
        </div>
      </div>
    );
  };

  const renderUploadStep = () => (
    <div className="mt-6">
      <div
        className={`border-2 border-dashed rounded-lg p-8 text-center ${uploadedFile && validationPassed
          ? "border-emerald-700"
          : "border-gray-300 hover:border-gray-400"
          } transition-colors duration-200`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
      >
        {!uploadedFile ? (
          <div>
            <Upload className="mx-auto h-12 w-12 text-gray-400" />
            <div className="mt-4 flex text-sm text-gray-600 justify-center">
              <label
                htmlFor="file-upload"
                className="relative cursor-pointer rounded-md font-medium text-emerald-700 hover:text-emerald-600 focus-within:outline-none"
              >
                <span>Upload a file</span>
                <input
                  id="file-upload"
                  name="file-upload"
                  type="file"
                  className="sr-only"
                  accept="image/*"
                  onChange={handleFileChange}
                />
              </label>
              <p className="pl-1">or drag and drop</p>
            </div>
            <p className="text-xs text-emerald-500 mt-2">
              PNG, JPG, GIF up to 10MB
            </p>
          </div>
        ) : (
          <div>
            {validationPassed && previewUrl ? (
              <div className="relative mx-auto w-64 h-64 mb-4">
                <img
                  src={previewUrl || ""}
                  alt="Preview"
                  className="w-full h-full object-contain rounded"
                />
                <button
                  type="button"
                  className="absolute top-0 right-0 -mt-2 -mr-2 bg-red-600 rounded-full p-1 text-white shadow-sm hover:bg-red-700 focus:outline-none"
                  onClick={handleRemoveFile}
                >
                  <X className="h-4 w-4 text-white" />
                </button>
              </div>
            ) : (
              <div className="relative mx-auto w-64 h-64 mb-4 bg-gray-100 rounded flex items-center justify-center">
                <div className="text-center text-gray-400">
                  <ImageIcon className="mx-auto h-12 w-12" />
                  <p className="mt-2 text-sm">Validation in progress...</p>
                </div>
              </div>
            )}
            <p className="text-sm text-gray-600">{uploadedFile.name}</p>
            <p className="text-xs text-gray-500 mt-1">
              {(uploadedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        )}
      </div>

      {uploadedFile && (
        <div className="mt-6">
          <Button
            variant="contained"
            color="success"
            onClick={handleUpload}
            fullWidth
            className="!font-bold"
          >
            Continue to Details
          </Button>
        </div>
      )}
    </div>
  );

  const renderDetailsStep = () => (
    <form
      onSubmit={handleSubmit(
        onSubmit,
        (errors) => {
          // ✅ Handle form validation errors
          console.error("❌ Form validation failed:", errors);
          const errorFields = Object.keys(errors);
          if (errorFields.length > 0) {
            const firstError = errors[errorFields[0]];
            toast.error(
              firstError?.message || `Please fix errors in: ${errorFields.join(", ")}`
            );
          } else {
            toast.error("Please fill all required fields correctly.");
          }
        }
      )}
      className="mt-6 space-y-6"
    >
      {/* PSL Metadata Fields - Show only when PSL is enabled */}
      {isPSLTicket && (
        <div className="p-4 bg-green-50 border border-green-200 rounded-lg space-y-4">
          <h4 className="font-medium text-green-800 flex items-center gap-2">
            <Ticket className="w-4 h-4" />
            PSL Ticket Details
          </h4>
          
          <div className="grid grid-cols-2 gap-4">
            {/* Seat Number */}
            <div>
              <InputLabel htmlFor="seat_number">
                <Armchair className="w-4 h-4 inline mr-1" />
                Seat Number *
              </InputLabel>
              <Input
                id="seat_number"
                type="text"
                value={pslMetadata.seat_number}
                onChange={(e) => setPslMetadata({...pslMetadata, seat_number: e.target.value})}
                placeholder="e.g., A-45"
                fullWidth
                required={isPSLTicket}
              />
            </div>
            
            {/* Stand */}
            <div>
              <InputLabel htmlFor="stand">Stand/Section *</InputLabel>
              <select
                id="stand"
                value={pslMetadata.stand}
                onChange={(e) => setPslMetadata({...pslMetadata, stand: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-green-500 focus:border-green-500"
                required={isPSLTicket}
              >
                <option value="">Select Stand</option>
                {pslStands.map(stand => (
                  <option key={stand} value={stand}>{stand}</option>
                ))}
              </select>
            </div>
          </div>
          
          {/* Venue */}
          <div>
            <InputLabel htmlFor="venue">
              <MapPin className="w-4 h-4 inline mr-1" />
              Venue *
            </InputLabel>
            <select
              id="venue"
              value={pslMetadata.venue}
              onChange={(e) => setPslMetadata({...pslMetadata, venue: e.target.value})}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-green-500 focus:border-green-500"
              required={isPSLTicket}
            >
              {pslVenues.map(venue => (
                <option key={venue} value={venue}>{venue}</option>
              ))}
            </select>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            {/* Match Date */}
            <div>
              <InputLabel htmlFor="match_date">
                <Calendar className="w-4 h-4 inline mr-1" />
                Match Date *
              </InputLabel>
              <Input
                id="match_date"
                type="date"
                value={pslMetadata.match_date}
                onChange={(e) => setPslMetadata({...pslMetadata, match_date: e.target.value})}
                fullWidth
                required={isPSLTicket}
              />
            </div>
            
            {/* Match Time */}
            <div>
              <InputLabel htmlFor="match_time">
                <Clock className="w-4 h-4 inline mr-1" />
                Match Time *
              </InputLabel>
              <Input
                id="match_time"
                type="time"
                value={pslMetadata.match_time}
                onChange={(e) => setPslMetadata({...pslMetadata, match_time: e.target.value})}
                fullWidth
                required={isPSLTicket}
              />
            </div>
          </div>
        </div>
      )}

      <div>
        <InputLabel htmlFor="title">{isPSLTicket ? "Match Title *" : "Ticket Title *"}</InputLabel>
        <Input
          id="title"
          type="text"
          {...register("title")}
          error={!!errors.title}
          fullWidth
          placeholder={isPSLTicket ? "e.g., Peshawar Zalmi vs Quetta Gladiators" : "Enter ticket title"}
        />
        {errors.title && (
          <p className="mt-1 text-sm text-red-600">{errors.title.message}</p>
        )}
      </div>

      <div>
        <InputLabel htmlFor="description">Description *</InputLabel>
        <textarea
          id="description"
          rows={4}
          className="shadow-sm focus:ring-emerald-500 focus:border-emerald-500 block w-full sm:text-sm border-gray-300 rounded-md"
          {...register("description")}
          error={!!errors.description}
          fullWidth
          placeholder={isPSLTicket ? "Match details, special notes, etc." : "Describe your ticket"}
        />
        {errors.description && (
          <p className="mt-1 text-sm text-red-600">
            {errors.description.message}
          </p>
        )}
      </div>

       {/* Price Input with Currency Selection */}
       <div>
        <InputLabel htmlFor="price">{isPSLTicket ? "Ticket Price *" : "Price *"}</InputLabel>
        <div className="flex space-x-2">
          <div className="flex-1">
            <Input
              id="price"
              type="number"
              inputProps={{ 
                step: "any", 
                min: "0",
                // ✅ FIXED: Prevent value from being reset on blur
                onBlur: (e) => {
                  const value = e.target.value;
                  if (value && !isNaN(value) && parseFloat(value) > 0) {
                    // Preserve the value when user leaves the field
                    setValue("price", parseFloat(value), { shouldValidate: true });
                  }
                }
              }}
              {...register("price", {
                // ✅ FIXED: Add onChange handler to preserve value
                onChange: (e) => {
                  const value = e.target.value;
                  if (value !== "" && !isNaN(value)) {
                    setValue("price", value, { shouldValidate: false });
                  }
                },
                // ✅ FIXED: Add onBlur handler to ensure value is preserved
                onBlur: (e) => {
                  const value = e.target.value;
                  if (value && !isNaN(value) && parseFloat(value) > 0) {
                    setValue("price", parseFloat(value), { shouldValidate: true });
                  }
                }
              })}
              error={!!errors.price}
              fullWidth
              placeholder={priceInputMode === "usd" ? "Enter price in USD" : `Enter price in ${currencySymbol}`}
              // ✅ FIXED: Ensure value is controlled properly
              value={priceValue || ""}
            />
          </div>
          <div className="w-32">
            <select
              value={priceInputMode}
              onChange={(e) => {
                const newMode = e.target.value;
                const currentPrice = watch("price");
                
                // ✅ FIXED: Only convert if we have a valid price
                if (currentPrice && !isNaN(currentPrice) && currentPrice !== "" && currentPrice !== 0) {
                  if (newMode === "usd" && priceInputMode === "eth") {
                    // Converting from ETH to USD - convert the ETH price to USD
                    const usdPrice = CurrencyConverter.ethToUsd(parseFloat(currentPrice));
                    setValue("price", usdPrice.toFixed(2), { shouldValidate: true });
                  } else if (newMode === "eth" && priceInputMode === "usd") {
                    // Converting from USD to ETH - convert the USD price to ETH
                    const ethPrice = CurrencyConverter.usdToEth(parseFloat(currentPrice));
                    setValue("price", ethPrice.toFixed(6), { shouldValidate: true });
                  }
                }
                setPriceInputMode(newMode);
              }}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-emerald-500 focus:border-emerald-500"
            >
              <option value="eth">{currencySymbol}</option>
              <option value="usd">USD</option>
            </select>
          </div>
        </div>
        {errors.price && (
          <p className="mt-1 text-sm text-red-600">{errors.price.message}</p>
        )}
        {priceValue && !isNaN(priceValue) && parseFloat(priceValue) > 0 && (
          <p className="mt-1 text-sm text-gray-500">
            {priceInputMode === "usd" 
              ? `≈ ${CurrencyConverter.formatCrypto(CurrencyConverter.usdToEth(parseFloat(priceValue)), selectedNetwork)}`
              : `≈ ${CurrencyConverter.formatUsd(CurrencyConverter.ethToUsd(parseFloat(priceValue)))}`
            }
          </p>
        )}
      </div>

      <div className="mb-6">
        <InputLabel htmlFor="registration-method">Registration Method *</InputLabel>

        {!enableCrypto && !enablePayPal ? (
          <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm flex items-center">
            <AlertCircle className="w-4 h-4 mr-2" />
            Uploads are currently disabled by the administrator.
          </div>
        ) : (
          <select
            id="registration-method"
            value={registrationMethod}
            onChange={(e) => setRegistrationMethod(e.target.value)}
            disabled={isPSLTicket}
            className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-emerald-500 focus:border-emerald-500"
          >
            <option value="on-chain">On-chain (Blockchain)</option>
          </select>
        )}

        <p className="mt-1 text-xs text-gray-500">
          {isPSLTicket
            ? `PSL Smart-Tickets are restricted to on-chain registration using MetaMask on ${currentNetworkConfig.label}.`
            : `Register on blockchain using MetaMask (requires ${currencySymbol} for gas fees only)`}
        </p>

        {/* ✅ Show requirements based on selected method */}
        {registrationMethod === "on-chain" && requiresWallet && (
          <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
            <p className="text-sm text-yellow-800 font-medium mb-1">
              ⚠️ Wallet Connection Required
            </p>
            <p className="text-xs text-yellow-700">
              To register on-chain, you need to:
            </p>
            <ul className="text-xs text-yellow-700 mt-1 ml-4 list-disc">
              <li>Connect your MetaMask wallet</li>
              <li>Switch to {currentNetworkConfig.label}</li>
              <li>Have {currencySymbol} for gas fees and registration platform fee (if applicable)</li>
            </ul>
            {!isWalletConnected && (
              <button
                onClick={async () => {
                  const connected = await connectWallet();
                  if (connected && !isCorrectNetwork) {
                    await switchNetwork(selectedNetwork);
                  }
                }}
                className="mt-2 px-3 py-1 text-xs bg-yellow-600 text-white rounded hover:bg-yellow-700"
              >
                Connect Wallet
              </button>
            )}
          </div>
        )}

        {/* ✅ Show success message when requirements are met */}
        {registrationMethod === "on-chain" && !requiresWallet && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-sm text-green-800 font-medium">
              ✅ Ready to register on-chain
            </p>
            <p className="text-xs text-green-700 mt-1">
              Your wallet is connected and ready. You can proceed with registration.
            </p>
          </div>
        )}
      </div>

      {!isPSLTicket && (
        <div>
          <InputLabel htmlFor="royalty_percentage">
            Royalty Percentage *
          </InputLabel>
          <select
            id="royalty_percentage"
            className="block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-emerald-500 focus:border-emerald-500 sm:text-sm rounded-md"
            {...register("royalty_percentage")}
          >
            {loyaltyPercentage.map((option) => (
              <option key={option.id} value={option.value}>
                {option.percentage}
              </option>
            ))}
          </select>
          {errors.royalty_percentage && (
            <p className="mt-1 text-sm text-red-600">
              {errors.royalty_percentage.message}
            </p>
          )}
        </div>
      )}

      {/* Category Selection */}
      {!isPSLTicket && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Medium Category */}
          <div>
            <FormControl fullWidth>
              <InputLabel id="medium-category-label">
                🎨 Medium / Technique *
              </InputLabel>
              <Select
                id="medium_category"
                labelId="medium-category-label"
                label="🎨 Medium / Technique *"
                {...register("medium_category")}
                error={!!errors.medium_category}
                disabled={categoriesLoading.medium}
              >
                <MenuItem value="" disabled>
                  {categoriesLoading.medium ? "Loading..." : "Select a medium"}
                </MenuItem>
                {categories.medium.map((category) => (
                  <MenuItem
                    key={category.id || category.name}
                    value={category.name}
                  >
                    {category.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {errors.medium_category && (
              <p className="mt-1 text-sm text-red-600">
                {errors.medium_category.message}
              </p>
            )}
            {showOtherMedium && (
              <div className="mt-2">
                <InputLabel htmlFor="other_medium">
                  Specify Other Medium
                </InputLabel>
                <Input
                  id="other_medium"
                  type="text"
                  {...register("other_medium")}
                  fullWidth
                  placeholder="Enter your medium"
                />
              </div>
            )}
          </div>

          {/* Style Category */}
          <div>
            <FormControl fullWidth>
              <InputLabel id="style-category-label">
                🖼 Style / Movement *
              </InputLabel>
              <Select
                id="style_category"
                labelId="style-category-label"
                label="🖼 Style / Movement *"
                {...register("style_category")}
                error={!!errors.style_category}
                disabled={categoriesLoading.style}
              >
                <MenuItem value="" disabled>
                  {categoriesLoading.style ? "Loading..." : "Select a style"}
                </MenuItem>
                {categories.style.map((category) => (
                  <MenuItem
                    key={category.id || category.name}
                    value={category.name}
                  >
                    {category.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {errors.style_category && (
              <p className="mt-1 text-sm text-red-600">
                {errors.style_category.message}
              </p>
            )}
            {showOtherStyle && (
              <div className="mt-2">
                <InputLabel htmlFor="other_style">Specify Other Style</InputLabel>
                <Input
                  id="other_style"
                  type="text"
                  {...register("other_style")}
                  fullWidth
                  placeholder="Enter your style"
                />
              </div>
            )}
          </div>

          {/* Subject Category */}
          <div>
            <FormControl fullWidth>
              <InputLabel id="subject-category-label">
                🌍 Subject Matter *
              </InputLabel>
              <Select
                id="subject_category"
                labelId="subject-category-label"
                label="🌍 Subject Matter *"
                {...register("subject_category")}
                error={!!errors.subject_category}
                disabled={categoriesLoading.subject}
              >
                <MenuItem value="" disabled>
                  {categoriesLoading.subject ? "Loading..." : "Select a subject"}
                </MenuItem>
                {categories.subject.map((category) => (
                  <MenuItem
                    key={category.id || category.name}
                    value={category.name}
                  >
                    {category.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {errors.subject_category && (
              <p className="mt-1 text-sm text-red-600">
                {errors.subject_category.message}
              </p>
            )}
            {showOtherSubject && (
              <div className="mt-2">
                <InputLabel htmlFor="other_subject">
                  Specify Other Subject
                </InputLabel>
                <Input
                  id="other_subject"
                  type="text"
                  {...register("other_subject")}
                  fullWidth
                  placeholder="Enter your subject"
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Show error message if categories failed to load */}
      {(categories.medium.some((cat) => cat.id === "error") ||
        categories.style.some((cat) => cat.id === "error") ||
        categories.subject.some((cat) => cat.id === "error")) && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-600">
              Failed to load categories. Please refresh the page or try again
              later.
            </p>
          </div>
        )}

      {/* Responsible Use Addon Switch - REDESIGNED */}
      {!isPSLTicket && (
        <div 
          ref={addonRef}
          className={`p-6 rounded-2xl border-2 transition-all duration-300 ${
            responsibleUseAddon 
              ? "bg-emerald-50 border-emerald-200 shadow-md transform scale-[1.01]" 
              : "bg-gray-50 border-gray-100 opacity-80 hover:opacity-100"
          }`}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-2">
                <div className={`p-2 rounded-lg transition-colors ${
                  responsibleUseAddon ? "bg-emerald-600 text-white" : "bg-gray-200 text-gray-500"
                }`}>
                  <Shield size={20} />
                </div>
                <h4 className={`text-lg font-bold transition-colors ${
                  responsibleUseAddon ? "text-emerald-900" : "text-gray-700"
                }`}>
                  Responsible Use Addon
                </h4>
                {responsibleUseAddon && (
                  <span className="bg-emerald-600 text-white text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider animate-pulse">
                    Enabled
                  </span>
                )}
              </div>
              <p className={`text-sm leading-relaxed transition-colors ${
                responsibleUseAddon ? "text-emerald-700" : "text-gray-500"
              }`}>
                Allow your {isPSLTicket ? "image" : "ticket"} to be used for responsible AI training and non-commercial ethical usage. 
                This helps build a safer creative ecosystem while earning you a small additional surcharge.
              </p>
            </div>
            <div className="flex flex-col items-center gap-2">
              <Switch
                checked={responsibleUseAddon}
                onChange={(e) => setResponsibleUseAddon(e.target.checked)}
                color="success"
                className="transform scale-125"
              />
              <span className="text-[10px] font-bold text-gray-400 uppercase">
                {responsibleUseAddon ? "Active" : "Off"}
              </span>
            </div>
          </div>
          
          {responsibleUseAddon && (
            <div className="mt-4 pt-4 border-t border-emerald-100 flex items-center gap-2 text-xs text-emerald-600 font-medium animate-in slide-in-from-top-2">
              <CheckCircle size={14} />
              Addon will be registered on the blockchain with your {isPSLTicket ? "ticket" : "ticket"}.
            </div>
          )}
        </div>
      )}

      <Button
        type="submit"
        variant="contained"
        color="success"
        fullWidth
        className="!font-bold"
        disabled={isSubmitting}
        onClick={(e) => {
          // ✅ Log for debugging
          console.log("Register button clicked:", {
            registrationMethod,
            validationPassed,
            isSubmitting,
            formData: watch(),
            errors: errors,
            hasImage: !!uploadedFile
          });

          console.log("Allowing form submission...");
        }}
      >
        {isSubmitting ? (
          <div className="flex items-center justify-center">
            <LoadingSpinner size="small" text="" />
            <span className="ml-2">Registering...</span>
          </div>
        ) : (
          isPSLTicket 
            ? `Register PSL Ticket (${registrationMethod === 'on-chain' ? 'On-chain' : 'Off-chain'})`
            : `Register Your Ticket (${registrationMethod === 'on-chain' ? 'On-chain' : 'Off-chain'})`
        )}
      </Button>
    </form>
  );

  const renderBlockchainStep = () => (
    <div className="mt-8 text-center">
      <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-emerald-700 mx-auto"></div>
      <h3 className="mt-6 text-lg font-medium text-gray-900">
        Registering your {isPSLTicket ? "ticket" : "ticket"} on blockchain
      </h3>
      <p className="mt-2 text-sm text-gray-500">
        This may take a few moments...
      </p>

      <div className="mt-6 flex justify-center space-x-4">
        <div className="text-center">
          <div className="flex items-center justify-center w-8 h-8 mx-auto rounded-full bg-green-100 text-green-600">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <p className="mt-1 text-xs text-gray-500">Upload</p>
        </div>

        <div className="text-center">
          <div className="flex items-center justify-center w-8 h-8 mx-auto rounded-full bg-green-100 text-green-600">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <p className="mt-1 text-xs text-gray-500">Details</p>
        </div>

        <div className="text-center">
          <div className="flex items-center justify-center w-8 h-8 mx-auto rounded-full bg-emerald-100 text-emerald-700">
            <span className="text-sm font-bold">3</span>
          </div>
          <p className="mt-1 text-xs text-gray-500">Register</p>
        </div>
      </div>
    </div>
  );

  const renderCompleteStep = () => (
    <div className="mt-8 text-center">
      <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100">
        <svg
          className="h-6 w-6 text-green-600"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M5 13l4 4L19 7"
          />
        </svg>
      </div>
      <h3 className="mt-6 text-lg font-medium text-gray-900">
        {isPSLTicket ? "Ticket" : "Ticket"} has been registered!
      </h3>
      <p className="mt-2 text-sm text-gray-500">
        Your {isPSLTicket ? "ticket" : "ticket"} is now on the blockchain and ready to be licensed
      </p>

      {transactionHash && (
        <div className="mt-4 p-3 bg-gray-50 rounded-lg">
          <p className="text-xs text-gray-600">Transaction Hash:</p>
          <p className="text-xs font-mono text-gray-800 break-all">
            {transactionHash}
          </p>
          <button
            type="button"
            onClick={() => {
              navigator.clipboard.writeText(transactionHash);
              toast.success("Transaction hash copied to clipboard");
            }}
            className="mt-1 text-xs text-emerald-600 hover:text-emerald-800 flex items-center justify-center"
          >
            <Copy className="w-3 h-3 mr-1" /> Copy
          </button>
        </div>
      )}

      <div className="mt-6 flex space-x-4">
        <Button
          variant="outlined"
          color="success"
          fullWidth
          onClick={() => {
            // Clear draft from localStorage
            localStorage.removeItem('ticket_upload_draft');
            setCurrentStep("upload");
            reset();
            setUploadedFile(null);
            setPreviewUrl(null);
            setDuplicateCheck(null);
            setAiClassification(null);
            setValidationPassed(false);
          }}
          className="!font-bold"
        >
          Upload Another
        </Button>
        <Button
          variant="contained"
          color="success"
          fullWidth
          onClick={() => navigate("/dashboard/psl-tickets")}
          className="!font-bold !ms-2"
        >
          View My {isPSLTicket ? "Tickets" : "Tickets"}
        </Button>
      </div>
    </div>
  );

  // ✅ Don't block access - show requirements during registration flow instead
  const requiresWallet = registrationMethod === "on-chain" && !isWalletConnected;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          {isPSLTicket ? "Upload PSL Smart-Ticket" : "Upload Ticket"}
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          {isPSLTicket 
            ? "Issue a secure, DRM-protected ticket for your match or event"
            : "Register your digital creation on the blockchain to protect your ownership"}
        </p>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {/* Progress Steps */}
        <div className="px-6 py-4 border-b border-gray-200">
          <nav className="flex justify-between">
            <button
              type="button"
              className={`text-sm font-medium ${currentStep === "upload" ? "text-emerald-700" : "text-gray-500"
                }`}
              disabled={true}
            >
              <span
                className={`rounded-full w-8 h-8 inline-flex items-center justify-center mr-2 ${currentStep === "upload"
                  ? "bg-emerald-700 text-white"
                  : "bg-gray-200 text-gray-600"
                  }`}
              >
                1
              </span>
              Upload
            </button>
            <div className="hidden sm:block w-10 h-0.5 self-center bg-gray-200"></div>
            <button
              type="button"
              className={`text-sm font-medium ${currentStep === "details" ? "text-emerald-700" : "text-gray-500"
                }`}
              disabled={true}
            >
              <span
                className={`rounded-full w-8 h-8 inline-flex items-center justify-center mr-2 ${currentStep === "details"
                  ? "bg-emerald-700 text-white"
                  : "bg-gray-200 text-gray-600"
                  }`}
              >
                2
              </span>
              Details
            </button>
            <div className="hidden sm:block w-10 h-0.5 self-center bg-gray-200"></div>
            <button
              type="button"
              className={`text-sm font-medium ${currentStep === "blockchain" || currentStep === "complete"
                ? "text-emerald-700"
                : "text-gray-500"
                }`}
              disabled={true}
            >
              <span
                className={`rounded-full w-8 h-8 inline-flex items-center justify-center mr-2 ${currentStep === "blockchain" || currentStep === "complete"
                  ? "bg-emerald-700 text-white"
                  : "bg-gray-200 text-gray-600"
                  }`}
              >
                3
              </span>
              Register
            </button>
          </nav>
        </div>

        <div className="px-6 py-6">
          {currentStep === "upload" && renderUploadStep()}
          {currentStep === "details" && renderDetailsStep()}
          {currentStep === "blockchain" && renderBlockchainStep()}
          {currentStep === "complete" && renderCompleteStep()}
        </div>
      </div>
    </div>
  );
};

export default UploadTickets;