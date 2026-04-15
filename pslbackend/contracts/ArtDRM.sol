// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/interfaces/IERC2981.sol";

/// @title XDRM - Digital Rights Management for Artworks
/// @author XDRM Team
/// @notice A comprehensive NFT platform for artwork registration, licensing, and sales with royalty support
/// @dev Implements ERC721 with URI storage, ERC2981 royalty standard, pause mechanism, and reentrancy protection.
///      All fees are pre-calculated by backend and passed to contract functions for gas optimization.
contract XDRM is ERC721URIStorage, IERC2981, ReentrancyGuard, Ownable, Pausable {
    
    /// @notice Custom error thrown when input parameters are invalid
    error InvalidInput();
    
    /// @notice Custom error thrown when artwork token ID does not exist
    error ArtworkNotFound();
    
    /// @notice Custom error thrown when caller is not authorized to perform the action
    error Unauthorized();
    
    /// @notice Custom error thrown when payment amount is insufficient
    error InsufficientPayment();
    
    /// @notice Custom error thrown when license is not found
    error LicenseNotFound();
    
    /// @notice Structure storing artwork information
    /// @param creator Address of the artwork creator
    /// @param metadataURI IPFS or decentralized storage URI for artwork metadata
    /// @param royaltyPercentage Royalty percentage in basis points (100 = 1%, 1000 = 10%)
    /// @param isLicensed Boolean indicating if artwork has any active licenses
    struct ArtworkInfo {
        address creator;
        string metadataURI;
        uint256 royaltyPercentage;
        bool isLicensed;
    }
    
    /// @notice Structure storing license information
    /// @param tokenId The artwork token ID this license belongs to
    /// @param licensee Address of the license holder
    /// @param startDate License start timestamp
    /// @param endDate License expiration timestamp
    /// @param termsHash Hash of license terms (stored off-chain)
    /// @param licenseType Type of license: PERSONAL, COMMERCIAL, or EXCLUSIVE
    /// @param isActive Boolean indicating if license is currently active
    /// @param feePaid Amount paid for this license in wei
    struct License {
        uint256 tokenId;
        address licensee;
        uint256 startDate;
        uint256 endDate;
        string termsHash;
        LicenseType licenseType;
        Duration duration; // ✅ Added Duration enum
        bool isActive;
        uint256 feePaid;
    }
    
    /// @notice Structure for efficient license lookup (O(1) access)
    /// @param tokenId The artwork token ID
    /// @param index Array index in tokenLicenses mapping
    struct LicenseLocation {
        uint128 tokenId;
        uint128 index;
    }
    
    /// @notice License type enumeration
    /// @dev Support for 8 granular DRM license tiers
    enum LicenseType { 
        PERSONAL_USE,
        NON_COMMERCIAL,
        COMMERCIAL,
        EXTENDED_COMMERCIAL,
        EXCLUSIVE,
        ARTWORK_OWNERSHIP,
        CUSTOM
    }

    /// @notice License duration enumeration
    /// @dev Explicit tiers for duration consistency
    enum Duration { 
        MONTHLY,    // 0: 30 days
        QUARTERLY,  // 1: 90 days
        PERPETUAL   // 2: Lifetime (36500 days)
    }
    
    uint256 private _currentTokenId;
    
    /// @notice Maximum royalty percentage allowed (20% = 2000 basis points)
    uint256 public constant MAX_ROYALTY = 2000;

    
    mapping(uint256 => ArtworkInfo) public artworks;
    mapping(uint256 => License[]) public tokenLicenses;
    mapping(address => uint256[]) public creatorArtworks;
    mapping(uint256 => LicenseLocation) public licenseLocations;
    mapping(uint256 => address) public exclusiveLicenseHolder;
    uint256 private _licenseCounter;
    
    /// @notice Emitted when a new artwork is registered
    /// @param tokenId The newly minted token ID
    /// @param creator Address of the artwork creator
    /// @param metadataURI IPFS URI for artwork metadata
    /// @param royaltyPercentage Royalty percentage in basis points
    event ArtworkRegistered(uint256 indexed tokenId, address indexed creator, string metadataURI, uint256 royaltyPercentage);
    
    /// @notice Emitted when a license is granted or purchased
    /// @param licenseId The newly created license ID
    /// @param tokenId The artwork token ID
    /// @param licensee Address receiving the license
    /// @param licenseType Type of license granted
    /// @param duration License duration enum
    /// @param feePaid License fee amount in wei
    event LicenseGranted(uint256 indexed licenseId, uint256 indexed tokenId, address indexed licensee, LicenseType licenseType, Duration duration, uint256 feePaid);
    
    /// @notice Emitted when a license is revoked by artwork owner
    /// @param licenseId The revoked license ID
    /// @param tokenId The artwork token ID
    /// @param licensee Address whose license was revoked
    event LicenseRevoked(uint256 indexed licenseId, uint256 indexed tokenId, address indexed licensee);
    
    /// @notice Emitted when royalty is paid to creator during secondary sale
    /// @param tokenId The artwork token ID
    /// @param creator Address of the creator receiving royalty
    /// @param amount Royalty amount paid in wei
    event RoyaltyPaid(uint256 indexed tokenId, address indexed creator, uint256 amount);
    
    /// @notice Contract constructor
    /// @dev Initializes ERC721 with name "XDRM" and symbol "XDRM"
    constructor() ERC721("XDRM", "XDRM") {
    }
    
    /// @notice Register a new artwork as an NFT
    /// @dev Mints a new NFT token, stores artwork metadata, and transfers registration fee to contract owner.
    ///      Excess payment is automatically refunded to sender.
    /// @param metadataURI IPFS or other decentralized storage URI containing artwork metadata
    /// @param royaltyPercentage Royalty percentage in basis points (e.g., 1000 = 10%, max 2000 = 20%)
    /// @param registrationFeeWei Registration fee amount in wei (pre-calculated by backend)
    /// @return tokenId The newly minted token ID
    /// @custom:security nonReentrant Prevents reentrancy attacks
    /// @custom:security whenNotPaused Only works when contract is not paused
    function registerArtwork(
        string memory metadataURI,
        uint256 royaltyPercentage,
        uint256 registrationFeeWei
    ) external payable whenNotPaused nonReentrant returns (uint256) {
        if (royaltyPercentage > MAX_ROYALTY || bytes(metadataURI).length == 0) revert InvalidInput();
        if (msg.value < registrationFeeWei) revert InsufficientPayment();

        uint256 tokenId = _currentTokenId++;
        _safeMint(msg.sender, tokenId);
        _setTokenURI(tokenId, metadataURI);
        
        address contractOwner = owner();
        artworks[tokenId] = ArtworkInfo({
            creator: msg.sender,
            metadataURI: metadataURI,
            royaltyPercentage: royaltyPercentage,
            isLicensed: false
        });
        creatorArtworks[msg.sender].push(tokenId);
        payable(contractOwner).transfer(registrationFeeWei);
    
        unchecked {
            uint256 excess = msg.value - registrationFeeWei;
            if (excess > 0) payable(msg.sender).transfer(excess);
        }
        
        emit ArtworkRegistered(tokenId, msg.sender, metadataURI, royaltyPercentage);
        return tokenId;
    }
    
    /// @notice Revoke an active license for an artwork
    /// @dev Artwork owner can revoke licenses. Updates isLicensed flag if no active licenses remain.
    /// @param tokenId The artwork token ID
    /// @param licensee Address whose license should be revoked
    /// @custom:security Only artwork owner can revoke licenses
    function revokeLicense(uint256 tokenId, address licensee) external {
        if (!_exists(tokenId)) revert ArtworkNotFound();
        if (ownerOf(tokenId) != msg.sender) revert Unauthorized();
        
        License[] storage licenses = tokenLicenses[tokenId];
        uint256 length = licenses.length;
        bool found = false;
        uint256 licenseIndex = 0;
        
        for (uint256 i = 0; i < length; ) {
            if (licenses[i].licensee == licensee && licenses[i].isActive) {
                licenses[i].isActive = false;
                
                // Clear exclusive holder if an exclusive license is revoked
                if (licenses[i].licenseType == LicenseType.EXCLUSIVE || licenses[i].licenseType == LicenseType.ARTWORK_OWNERSHIP) {
                    if (exclusiveLicenseHolder[tokenId] == licensee) {
                        exclusiveLicenseHolder[tokenId] = address(0);
                    }
                }
                
                found = true;
                licenseIndex = i;
                break;
            }
            unchecked { ++i; }
        }
        
        if (!found) revert LicenseNotFound();
        emit LicenseRevoked(licenseIndex, tokenId, licensee);
        
        uint256 currentTime = block.timestamp;
        bool hasActiveLicense = false;
        for (uint256 i = 0; i < length; ) {
            License storage license = licenses[i];
            if (license.isActive && currentTime <= license.endDate) {
                hasActiveLicense = true;
                break;
            }
            unchecked { ++i; }
        }
        artworks[tokenId].isLicensed = hasActiveLicense;
    }

    /// @notice Purchase a license for an artwork (self-service)
    /// @dev Allows anyone (except artwork owner) to purchase a license. Fees are distributed:
    ///      artwork owner receives (licenseFee - sellerPlatformFee), platform receives (buyerPlatformFee + sellerPlatformFee).
    ///      Excess payment is automatically refunded.
    /// @param tokenId The artwork token ID
    /// @param durationDays License duration in days
    /// @param termsHash Hash of license terms (stored off-chain)
    /// @param licenseType License type: 0=PERSONAL, 1=COMMERCIAL, 2=EXCLUSIVE
    /// @param licenseFeeWei License fee amount in wei
    /// @param buyerPlatformFeeWei Platform fee paid by buyer in wei
    /// @param sellerPlatformFeeWei Platform fee deducted from seller in wei
    /// @return licenseId The newly created license ID
    /// @custom:security nonReentrant Prevents reentrancy attacks
    /// @custom:security whenNotPaused Only works when contract is not paused
    function purchaseLicense(
        uint256 tokenId,
        uint256 durationDays,
        string memory termsHash,
        LicenseType licenseType,
        uint256 licenseFeeWei,
        uint256 buyerPlatformFeeWei,
        uint256 sellerPlatformFeeWei
    ) external payable whenNotPaused nonReentrant returns (uint256) {
        if (!_exists(tokenId)) revert ArtworkNotFound();
        
        address artworkOwner = ownerOf(tokenId);
        address buyer = msg.sender;
        if (buyer == artworkOwner || buyer == address(0) || durationDays == 0) revert InvalidInput();
        
        // Enforce Exclusive License constraints
        if (exclusiveLicenseHolder[tokenId] != address(0)) revert Unauthorized(); // Already exclusively licensed
        
        if (licenseType == LicenseType.EXCLUSIVE || licenseType == LicenseType.ARTWORK_OWNERSHIP) {
            // Cannot buy exclusive if someone already holds an active license
            if (artworks[tokenId].isLicensed) revert InvalidInput(); 
            exclusiveLicenseHolder[tokenId] = buyer;
        }

        uint256 totalRequired = licenseFeeWei + buyerPlatformFeeWei;
        if (msg.value < totalRequired) revert InsufficientPayment();
        
        if (msg.value < totalRequired) revert InsufficientPayment(); // Corrected revert message
        
        // ✅ Calculate end date based on durationDays and determine Duration enum
        Duration durationEnum;
        uint256 durationInDays;
        if (durationDays <= 30) {
            durationEnum = Duration.MONTHLY;
            durationInDays = 30;
        } else if (durationDays <= 90) {
            durationEnum = Duration.QUARTERLY;
            durationInDays = 90;
        } else { // Duration.PERPETUAL
            durationEnum = Duration.PERPETUAL;
            durationInDays = 36500; // Lifetime (approx 100 years)
        }

        uint256 licenseId = _licenseCounter++;
        uint256 currentIndex = tokenLicenses[tokenId].length;
        licenseLocations[licenseId] = LicenseLocation({
            tokenId: uint128(tokenId),
            index: uint128(currentIndex)
        });

        uint256 startDate = block.timestamp;
        uint256 endDate = startDate + (durationInDays * 1 days);
        
        tokenLicenses[tokenId].push(License({
            tokenId: tokenId,
            licensee: buyer,
            startDate: startDate,
            endDate: endDate,
            termsHash: termsHash,
            licenseType: licenseType,
            duration: durationEnum,
            isActive: true,
            feePaid: licenseFeeWei
        }));
        artworks[tokenId].isLicensed = true;
        
        address contractOwner = owner();
        unchecked {
            payable(artworkOwner).transfer(licenseFeeWei - sellerPlatformFeeWei);
        }
        payable(contractOwner).transfer(buyerPlatformFeeWei + sellerPlatformFeeWei);
        
        // Update exclusivity if applicable
        if (licenseType == LicenseType.EXCLUSIVE || licenseType == LicenseType.ARTWORK_OWNERSHIP) {
            exclusiveLicenseHolder[tokenId] = buyer;
        }

        unchecked {
            uint256 excess = msg.value - totalRequired;
            if (excess > 0) payable(buyer).transfer(excess);
        }
        
        emit LicenseGranted(licenseId, tokenId, buyer, licenseType, durationEnum, licenseFeeWei);
        return licenseId;
    }
    
    /// @notice Handle artwork sale (primary or secondary)
    /// @dev Transfers NFT ownership and distributes funds. Primary sale: creator receives (salePrice - sellerPlatformFee).
    ///      Secondary sale: creator receives royalty, seller receives (salePrice - royalty - sellerPlatformFee).
    ///      Platform receives (buyerPlatformFee + sellerPlatformFee) in both cases. Excess payment is refunded.
    /// @param tokenId The artwork token ID
    /// @param salePrice Sale price in wei
    /// @param buyerPlatformFeeWei Platform fee paid by buyer in wei
    /// @param sellerPlatformFeeWei Platform fee deducted from seller in wei
    /// @custom:security nonReentrant Prevents reentrancy attacks
    /// @custom:security whenNotPaused Only works when contract is not paused
    function handleSale(
        uint256 tokenId, 
        uint256 salePrice,
        uint256 buyerPlatformFeeWei,
        uint256 sellerPlatformFeeWei
    ) external payable whenNotPaused nonReentrant {
        if (!_exists(tokenId)) revert ArtworkNotFound();
        
        uint256 totalRequired = salePrice + buyerPlatformFeeWei;
        if (msg.value < totalRequired) revert InsufficientPayment();
        
        address currentOwner = ownerOf(tokenId);
        ArtworkInfo storage artwork = artworks[tokenId];
        address creator = artwork.creator;
        address contractOwner = owner();
        
        _transfer(currentOwner, msg.sender, tokenId);
        
        if (currentOwner == creator) {
            // Primary sale: creator to buyer
            unchecked {
                payable(creator).transfer(salePrice - sellerPlatformFeeWei);
            }
            payable(contractOwner).transfer(buyerPlatformFeeWei + sellerPlatformFeeWei);
        } else {
            // Secondary sale: royalty to creator
            uint256 royaltyAmount = (salePrice * artwork.royaltyPercentage) / 10000;
            unchecked {
                payable(creator).transfer(royaltyAmount);
                payable(currentOwner).transfer(salePrice - royaltyAmount - sellerPlatformFeeWei);
            }
            payable(contractOwner).transfer(buyerPlatformFeeWei + sellerPlatformFeeWei);
            emit RoyaltyPaid(tokenId, creator, royaltyAmount);
        }
        
        unchecked {
            uint256 excess = msg.value - totalRequired;
            if (excess > 0) payable(msg.sender).transfer(excess);
        }
    }
    
    /// @notice Get artwork information
    /// @param tokenId The artwork token ID
    /// @return creator Address of the artwork creator
    /// @return metadataURI IPFS URI for artwork metadata
    /// @return royaltyPercentage Royalty percentage in basis points
    /// @return isLicensed Boolean indicating if artwork has active licenses
    function getArtworkInfo(uint256 tokenId) 
        external 
        view 
        returns (address creator, string memory metadataURI, uint256 royaltyPercentage, bool isLicensed) 
    {
        if (!_exists(tokenId)) revert ArtworkNotFound();
        ArtworkInfo memory artwork = artworks[tokenId];
        return (artwork.creator, artwork.metadataURI, artwork.royaltyPercentage, artwork.isLicensed);
    }
    
    /// @notice Get all active licenses for an artwork
    /// @dev Returns only licenses that are active and not expired
    /// @param tokenId The artwork token ID
    /// @return Array of active License structs
    function getActiveLicenses(uint256 tokenId) external view returns (License[] memory) {
        if (!_exists(tokenId)) revert ArtworkNotFound();
        
        License[] memory allLicenses = tokenLicenses[tokenId];
        uint256 length = allLicenses.length;
        uint256 currentTime = block.timestamp;
        uint256 activeCount = 0;
        uint256[] memory activeIndices = new uint256[](length);
        
        for (uint256 i = 0; i < length; ) {
            if (allLicenses[i].isActive && currentTime <= allLicenses[i].endDate) {
                activeIndices[activeCount] = i;
                unchecked { ++activeCount; }
            }
            unchecked { ++i; }
        }
        
        License[] memory activeLicenses = new License[](activeCount);
        for (uint256 i = 0; i < activeCount; ) {
            activeLicenses[i] = allLicenses[activeIndices[i]];
            unchecked { ++i; }
        }
        return activeLicenses;
    }
    
    /// @notice Get all artwork token IDs created by an address
    /// @param creator Address of the creator
    /// @return Array of token IDs created by the address
    function getCreatorArtworks(address creator) external view returns (uint256[] memory) {
        return creatorArtworks[creator];
    }
    
    /// @notice Get the current token ID counter
    /// @dev Returns the next token ID that will be minted
    /// @return Current token ID counter value
    function getCurrentTokenId() external view returns (uint256) {
        return _currentTokenId;
    }

    /// @notice Get detailed license information by license ID
    /// @dev Uses LicenseLocation mapping for O(1) lookup
    /// @param licenseId The license ID
    /// @return tokenId The artwork token ID
    /// @return owner Current owner of the artwork
    /// @return buyer Licensee address
    /// @return actualAmount License fee paid (same as licenseFee for compatibility)
    /// @return licenseFee License fee paid in wei
    /// @return totalAmount Total amount paid (same as licenseFee for compatibility)
    /// @return purchaseTime License start timestamp
    /// @return licenseType Type of license
    /// @return isActive Boolean indicating if license is active and not expired
    function getLicenseInfo(uint256 licenseId) external view returns (
        uint256 tokenId,
        address owner,
        address buyer,
        uint256 actualAmount,
        uint256 licenseFee,
        uint256 totalAmount,
        uint256 purchaseTime,
        LicenseType licenseType,
        bool isActive
    ) {
        LicenseLocation memory location = licenseLocations[licenseId];
        uint256 locationTokenId = uint256(location.tokenId);
        uint256 locationIndex = uint256(location.index);
        
        if (locationTokenId >= _currentTokenId) revert LicenseNotFound();
        if (locationIndex >= tokenLicenses[locationTokenId].length) revert LicenseNotFound();
        
        License memory license = tokenLicenses[locationTokenId][locationIndex];
        address artworkOwner = ownerOf(locationTokenId);
        
        return (
            license.tokenId,
            artworkOwner,
            license.licensee,
            license.feePaid,
            license.feePaid,
            license.feePaid,
            license.startDate,
            license.licenseType,
            license.isActive && block.timestamp <= license.endDate
        );
    }
    
    /// @notice Check if a license is valid for a specific address
    /// @param tokenId The artwork token ID
    /// @param licensee Address to check license for
    /// @return true if license exists, is active, and not expired
    function isLicenseValid(uint256 tokenId, address licensee) external view returns (bool) {
        if (!_exists(tokenId)) revert ArtworkNotFound();
        
        License[] memory licenses = tokenLicenses[tokenId];
        uint256 length = licenses.length;
        uint256 currentTime = block.timestamp;
        
        for (uint256 i = 0; i < length; ) {
            License memory license = licenses[i];
            if (license.licensee == licensee && license.isActive && currentTime <= license.endDate) {
                return true;
            }
            unchecked { ++i; }
        }
        return false;
    }
    
    /// @notice Get royalty information for ERC2981 standard
    /// @dev Implements IERC2981 interface for royalty support
    /// @param tokenId The artwork token ID
    /// @param salePrice Sale price in wei
    /// @return receiver Address to receive royalty (always the creator)
    /// @return royaltyAmount Royalty amount in wei
    function royaltyInfo(uint256 tokenId, uint256 salePrice)
        external
        view
        override
        returns (address receiver, uint256 royaltyAmount)
    {
        if (!_exists(tokenId)) revert ArtworkNotFound();
        ArtworkInfo storage artwork = artworks[tokenId];
        return (artwork.creator, (salePrice * artwork.royaltyPercentage) / 10000);
    }
    
    /// @notice Withdraw contract balance to owner
    /// @dev Only owner can withdraw. Used for emergency fund recovery.
    /// @custom:security onlyOwner Only contract owner can call
    function withdrawBalance() external onlyOwner {
        uint256 balance = address(this).balance;
        if (balance == 0) revert InvalidInput();
        payable(owner()).transfer(balance);
    }

    /// @notice Receive function to accept direct ETH transfers
    /// @dev Allows contract to receive ETH without function call. Used for emergency funds.
    receive() external payable {}

    /// @notice Pause the contract (emergency stop)
    /// @dev Only owner can pause. Stops all state-changing functions (registerArtwork, purchaseLicense, handleSale).
    /// @custom:security onlyOwner Only contract owner can pause
    function pause() external onlyOwner {
        _pause();
    }

    /// @notice Unpause the contract (resume operations)
    /// @dev Only owner can unpause. Resumes all functions.
    /// @custom:security onlyOwner Only contract owner can unpause
    function unpause() external onlyOwner {
        _unpause();
    }
    
    /// @notice Check if contract supports an interface (ERC165)
    /// @dev Implements ERC165 and ERC2981 interface detection
    /// @param interfaceId The interface identifier
    /// @return true if interface is supported
    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721URIStorage, IERC165)
        returns (bool)
    {
        return interfaceId == type(IERC2981).interfaceId || super.supportsInterface(interfaceId);
    }
}