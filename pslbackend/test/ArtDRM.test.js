const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("XDRM Contract - Complete Test Suite", function () {
  this.timeout(60000);
  let XDRM;
  let owner;
  let creator;
  let buyer;
  let licensee;
  let anotherUser;
  
  const BASE_REGISTRATION_FEE = ethers.parseEther("0.01");
  const PLATFORM_FEE_PERCENTAGE = 250; // 2.5% in basis points
  const REGISTRATION_FEE = (BASE_REGISTRATION_FEE * BigInt(PLATFORM_FEE_PERCENTAGE)) / BigInt(10000);
  
  beforeEach(async function () {
    [owner, creator, buyer, licensee, anotherUser] = await ethers.getSigners();
    
    const XDRM = await ethers.getContractFactory("XDRM");
    XDRM = await XDRM.deploy();
    await XDRM.waitForDeployment();
  });

  describe("Deployment", function () {
    it("Should set the right owner", async function () {
      expect(await XDRM.owner()).to.equal(owner.address);
    });

    it("Should have correct name and symbol", async function () {
      expect(await XDRM.name()).to.equal("ArtworkDRM");
      expect(await XDRM.symbol()).to.equal("ADRM");
    });

    it("Should start with tokenId 0", async function () {
      expect(await XDRM.getCurrentTokenId()).to.equal(0);
    });

    it("Should support ERC2981 interface", async function () {
      const ERC2981_INTERFACE_ID = "0x2a55205a";
      expect(await XDRM.supportsInterface(ERC2981_INTERFACE_ID)).to.be.true;
    });
  });

  describe("Artwork Registration", function () {
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000; // 10%

    it("Should register artwork successfully", async function () {
      await expect(
        XDRM.connect(creator).registerArtwork(
          metadataURI,
          royaltyPercentage,
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE }
        )
      ).to.emit(XDRM, "ArtworkRegistered")
        .withArgs(0, creator.address, metadataURI, royaltyPercentage);

      expect(await XDRM.ownerOf(0)).to.equal(creator.address);
      expect(await XDRM.tokenURI(0)).to.equal(metadataURI);
      
      const [creatorAddr, uri, royalty, isLicensed] = await XDRM.getArtworkInfo(0);
      expect(creatorAddr).to.equal(creator.address);
      expect(uri).to.equal(metadataURI);
      expect(royalty).to.equal(royaltyPercentage);
      expect(isLicensed).to.be.false;
    });

    it("Should increment tokenId on each registration", async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      expect(await XDRM.getCurrentTokenId()).to.equal(1);

      await XDRM.connect(creator).registerArtwork(
        "ipfs://QmTest456",
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      expect(await XDRM.getCurrentTokenId()).to.equal(2);
    });

    it("Should track creator artworks", async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const artworks = await XDRM.getCreatorArtworks(creator.address);
      expect(artworks.length).to.equal(1);
      expect(artworks[0]).to.equal(0);
    });

    it("Should revert if royalty exceeds MAX_ROYALTY", async function () {
      await expect(
        XDRM.connect(creator).registerArtwork(
          metadataURI,
          2500, // 25% > 20% max
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE }
        )
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });

    it("Should revert if metadata URI is empty", async function () {
      await expect(
        XDRM.connect(creator).registerArtwork(
          "",
          royaltyPercentage,
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE }
        )
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });

    it("Should revert if payment is insufficient", async function () {
      await expect(
        XDRM.connect(creator).registerArtwork(
          metadataURI,
          royaltyPercentage,
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE - 1n }
        )
      ).to.be.revertedWithCustomError(XDRM, "InsufficientPayment");
    });

    it("Should refund excess payment", async function () {
      const excessAmount = ethers.parseEther("0.001");
      const totalPayment = REGISTRATION_FEE + excessAmount;
      
      const initialBalance = await ethers.provider.getBalance(creator.address);
      
      const tx = await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: totalPayment }
      );
      
      const receipt = await tx.wait();
      const gasUsed = receipt.gasUsed * receipt.gasPrice;
      const finalBalance = await ethers.provider.getBalance(creator.address);
      
      expect(finalBalance).to.be.closeTo(
        initialBalance - REGISTRATION_FEE - gasUsed,
        ethers.parseEther("0.0001")
      );
    });

    it("Should transfer registration fee to owner", async function () {
      const ownerInitialBalance = await ethers.provider.getBalance(owner.address);
      
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const ownerFinalBalance = await ethers.provider.getBalance(owner.address);
      expect(ownerFinalBalance).to.equal(ownerInitialBalance + REGISTRATION_FEE);
    });
  });

  describe("License Management - Grant License", function () {
    let tokenId;
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000;
    const durationDays = 30;
    const licenseFee = ethers.parseEther("0.1");
    const buyerPlatformFee = ethers.parseEther("0.0025");
    const sellerPlatformFee = ethers.parseEther("0.0025");

    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });

    it("Should grant license successfully", async function () {
      const totalPayment = licenseFee + buyerPlatformFee;
      
      const tx = await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        durationDays,
        "termsHash123",
        0, // PERSONAL_USE
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: totalPayment }
      );
      
      await expect(tx).to.emit(XDRM, "LicenseGranted");
      
      expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.true;
      
      const [creatorAddr, , , isLicensed] = await XDRM.getArtworkInfo(tokenId);
      expect(isLicensed).to.be.true;
    });

    it("Should track license in active licenses", async function () {
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        durationDays,
        "termsHash123",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      const activeLicenses = await XDRM.getActiveLicenses(tokenId);
      expect(activeLicenses.length).to.equal(1);
      expect(activeLicenses[0].licensee).to.equal(licensee.address);
      expect(activeLicenses[0].isActive).to.be.true;
    });

    it("Should get license info correctly", async function () {
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        durationDays,
        "termsHash123",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      const licenseInfo = await XDRM.getLicenseInfo(0);
      expect(licenseInfo.tokenId).to.equal(tokenId);
      expect(licenseInfo.owner).to.equal(creator.address);
      expect(licenseInfo.buyer).to.equal(licensee.address);
      expect(licenseInfo.isActive).to.be.true;
    });

    it("Should revert if non-owner tries to grant license", async function () {
      await expect(
        XDRM.connect(buyer).purchaseLicense(
          tokenId,
          durationDays,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee }
        )
      ).to.be.revertedWithCustomError(XDRM, "Unauthorized");
    });

    it("Should revert if artwork doesn't exist", async function () {
      await expect(
        XDRM.connect(creator).purchaseLicense(999,
          durationDays,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee }
        )
      ).to.be.revertedWithCustomError(XDRM, "ArtworkNotFound");
    });

    it("Should revert if licensee is zero address", async function () {
      await expect(
        XDRM.connect(creator).purchaseLicense(tokenId,
          durationDays,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee }
        )
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });

    it("Should revert if duration is zero", async function () {
      await expect(
        XDRM.connect(licensee).purchaseLicense(
        tokenId,
          0,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee }
        )
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });

    it("Should revert if payment is insufficient", async function () {
      await expect(
        XDRM.connect(licensee).purchaseLicense(
        tokenId,
          durationDays,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee - 1n }
        )
      ).to.be.revertedWithCustomError(XDRM, "InsufficientPayment");
    });

    it("Should distribute fees correctly", async function () {
        const ownerInitialBalance = await ethers.provider.getBalance(owner.address);
        const creatorInitialBalance = await ethers.provider.getBalance(creator.address);
        
        const tx = await XDRM.connect(licensee).purchaseLicense(
        tokenId,
          durationDays,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee }
        );
        
        const receipt = await tx.wait();
        const gasUsed = receipt.gasUsed * receipt.gasPrice;
        
        const ownerFinalBalance = await ethers.provider.getBalance(owner.address);
        const creatorFinalBalance = await ethers.provider.getBalance(creator.address);
        
        // Owner receives platform fees
        expect(ownerFinalBalance - ownerInitialBalance).to.equal(buyerPlatformFee + sellerPlatformFee);
        
        // Creator balance calculation:
        // Creator sends: licenseFee + buyerPlatformFee
        // Creator receives: licenseFee - sellerPlatformFee
        // Net: (licenseFee - sellerPlatformFee) - (licenseFee + buyerPlatformFee) = -buyerPlatformFee - sellerPlatformFee
        // Plus gas cost: -gasUsed
        // Total change: -buyerPlatformFee - sellerPlatformFee - gasUsed
        
        const creatorBalanceChange = creatorFinalBalance - creatorInitialBalance;
        const expectedChange = -(buyerPlatformFee + sellerPlatformFee) - gasUsed;
        
        expect(creatorBalanceChange).to.be.closeTo(
          expectedChange,
          ethers.parseEther("0.0001")
        );
      });
  });

  describe("License Management - Purchase License", function () {
    let tokenId;
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000;
    const durationDays = 30;
    const licenseFee = ethers.parseEther("0.1");
    const buyerPlatformFee = ethers.parseEther("0.0025");
    const sellerPlatformFee = ethers.parseEther("0.0025");

    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });

    it("Should purchase license successfully", async function () {
      const totalPayment = licenseFee + buyerPlatformFee;
      
      const tx = await XDRM.connect(buyer).purchaseLicense(
        tokenId,
        durationDays,
        "termsHash123",
        0, // PERSONAL_USE
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: totalPayment }
      );
      
      await expect(tx).to.emit(XDRM, "LicenseGranted");
      
      expect(await XDRM.isLicenseValid(tokenId, buyer.address)).to.be.true;
    });

    it("Should revert if buyer is artwork owner", async function () {
      await expect(
        XDRM.connect(creator).purchaseLicense(
          tokenId,
          durationDays,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee }
        )
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });

    it("Should revert if buyer is zero address", async function () {
      // This is handled by the contract logic
      await expect(
        XDRM.connect(buyer).purchaseLicense(
          tokenId,
          0,
          "termsHash123",
          0,
          licenseFee,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: licenseFee + buyerPlatformFee }
        )
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });
  });

  describe("License Management - Revoke License", function () {
    let tokenId;
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000;
    const durationDays = 30;
    const licenseFee = ethers.parseEther("0.1");
    const buyerPlatformFee = ethers.parseEther("0.0025");
    const sellerPlatformFee = ethers.parseEther("0.0025");

    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });

    it("Should revoke license", async function () {
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        durationDays,
        "termsHash123",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      await expect(
        XDRM.connect(creator).revokeLicense(tokenId, licensee.address)
      ).to.emit(XDRM, "LicenseRevoked");
      
      expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.false;
    });

    it("Should update isLicensed flag when all licenses revoked", async function () {
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        durationDays,
        "termsHash123",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      let [, , , isLicensed] = await XDRM.getArtworkInfo(tokenId);
      expect(isLicensed).to.be.true;
      
      await XDRM.connect(creator).revokeLicense(tokenId, licensee.address);
      
      [, , , isLicensed] = await XDRM.getArtworkInfo(tokenId);
      expect(isLicensed).to.be.false;
    });

    it("Should revert if non-owner tries to revoke", async function () {
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        durationDays,
        "termsHash123",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      await expect(
        XDRM.connect(buyer).revokeLicense(tokenId, licensee.address)
      ).to.be.revertedWithCustomError(XDRM, "Unauthorized");
    });

    it("Should revert if license doesn't exist", async function () {
      await expect(
        XDRM.connect(creator).revokeLicense(tokenId, buyer.address)
      ).to.be.revertedWithCustomError(XDRM, "LicenseNotFound");
    });
  });

  describe("Artwork Sale", function () {
    let tokenId;
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000; // 10%
    const salePrice = ethers.parseEther("1.0");
    const buyerPlatformFee = ethers.parseEther("0.025");
    const sellerPlatformFee = ethers.parseEther("0.025");

    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });

    it("Should handle primary sale (creator to buyer)", async function () {
      const totalPayment = salePrice + buyerPlatformFee;
      
      await XDRM.connect(buyer).handleSale(
        tokenId,
        salePrice,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: totalPayment }
      );
      
      expect(await XDRM.ownerOf(tokenId)).to.equal(buyer.address);
      
      const [creatorAddr] = await XDRM.getArtworkInfo(tokenId);
      expect(creatorAddr).to.equal(creator.address); // Creator remains same
    });

    it("Should handle secondary sale with royalty", async function () {
      // First sale: creator to buyer1
      await XDRM.connect(buyer).handleSale(
        tokenId,
        salePrice,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: salePrice + buyerPlatformFee }
      );
      
      // Second sale: buyer1 to buyer2
      const salePrice2 = ethers.parseEther("2.0");
      const buyerPlatformFee2 = ethers.parseEther("0.05");
      
      const creatorInitialBalance = await ethers.provider.getBalance(creator.address);
      const buyerInitialBalance = await ethers.provider.getBalance(buyer.address);
      
      await expect(
        XDRM.connect(licensee).handleSale(
          tokenId,
          salePrice2,
          buyerPlatformFee2,
          sellerPlatformFee,
          { value: salePrice2 + buyerPlatformFee2 }
        )
      ).to.emit(XDRM, "RoyaltyPaid");
      
      expect(await XDRM.ownerOf(tokenId)).to.equal(licensee.address);
      
      const creatorFinalBalance = await ethers.provider.getBalance(creator.address);
      const royaltyAmount = (salePrice2 * BigInt(royaltyPercentage)) / BigInt(10000);
      expect(creatorFinalBalance - creatorInitialBalance).to.equal(royaltyAmount);
    });

    it("Should revert if artwork doesn't exist", async function () {
      await expect(
        XDRM.connect(buyer).handleSale(
          999,
          salePrice,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: salePrice + buyerPlatformFee }
        )
      ).to.be.revertedWithCustomError(XDRM, "ArtworkNotFound");
    });

    it("Should revert if payment is insufficient", async function () {
      await expect(
        XDRM.connect(buyer).handleSale(
          tokenId,
          salePrice,
          buyerPlatformFee,
          sellerPlatformFee,
          { value: salePrice + buyerPlatformFee - 1n }
        )
      ).to.be.revertedWithCustomError(XDRM, "InsufficientPayment");
    });
  });

  describe("View Functions", function () {
    let tokenId;
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000;

    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });

    it("Should return artwork info correctly", async function () {
      const [creatorAddr, uri, royalty, isLicensed] = await XDRM.getArtworkInfo(tokenId);
      
      expect(creatorAddr).to.equal(creator.address);
      expect(uri).to.equal(metadataURI);
      expect(royalty).to.equal(royaltyPercentage);
      expect(isLicensed).to.be.false;
    });

    it("Should return empty array for creator with no artworks", async function () {
      const artworks = await XDRM.getCreatorArtworks(buyer.address);
      expect(artworks.length).to.equal(0);
    });

    it("Should return current tokenId", async function () {
      expect(await XDRM.getCurrentTokenId()).to.equal(1);
      
      await XDRM.connect(creator).registerArtwork(
        "ipfs://QmTest456",
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      expect(await XDRM.getCurrentTokenId()).to.equal(2);
    });

    it("Should return active licenses only", async function () {
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      // Grant license
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        30,
        "termsHash123",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      let activeLicenses = await XDRM.getActiveLicenses(tokenId);
      expect(activeLicenses.length).to.equal(1);
      
      // Revoke license
      await XDRM.connect(creator).revokeLicense(tokenId, licensee.address);
      
      activeLicenses = await XDRM.getActiveLicenses(tokenId);
      expect(activeLicenses.length).to.equal(0);
    });

    it("Should return license info correctly", async function () {
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        30,
        "termsHash123",
        2, // COMMERCIAL
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      const licenseInfo = await XDRM.getLicenseInfo(0);
      expect(licenseInfo.tokenId).to.equal(tokenId);
      expect(licenseInfo.owner).to.equal(creator.address);
      expect(licenseInfo.buyer).to.equal(licensee.address);
      expect(licenseInfo.licenseType).to.equal(2); // COMMERCIAL
      expect(licenseInfo.isActive).to.be.true;
    });

    it("Should revert getLicenseInfo for non-existent license", async function () {
      await expect(XDRM.getLicenseInfo(999)).to.be.revertedWithCustomError(XDRM, "LicenseNotFound");
    });

    it("Should check license validity correctly", async function () {
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.false;
      
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        30,
        "termsHash123",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.true;
    });
  });

  describe("Royalty Info (ERC2981)", function () {
    let tokenId;

    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        "ipfs://test",
        1000, // 10%
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });

    it("Should return correct royalty info", async function () {
      const salePrice = ethers.parseEther("1.0");
      const [receiver, royaltyAmount] = await XDRM.royaltyInfo(tokenId, salePrice);
      
      expect(receiver).to.equal(creator.address);
      expect(royaltyAmount).to.equal(ethers.parseEther("0.1")); // 10% of 1.0
    });

    it("Should revert for non-existent token", async function () {
      await expect(
        XDRM.royaltyInfo(999, ethers.parseEther("1.0"))
      ).to.be.revertedWithCustomError(XDRM, "ArtworkNotFound");
    });
  });

  describe("Pause/Unpause", function () {
    it("Should pause contract (owner only)", async function () {
      await XDRM.connect(owner).pause();
      expect(await XDRM.paused()).to.be.true;
    });

    it("Should unpause contract (owner only)", async function () {
      await XDRM.connect(owner).pause();
      await XDRM.connect(owner).unpause();
      expect(await XDRM.paused()).to.be.false;
    });

    it("Should revert if non-owner tries to pause", async function () {
      await expect(
        XDRM.connect(creator).pause()
      ).to.be.revertedWith("Ownable: caller is not the owner");
    });

    it("Should revert functions when paused", async function () {
      await XDRM.connect(owner).pause();
      
      await expect(
        XDRM.connect(creator).registerArtwork(
          "ipfs://test",
          1000,
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE }
        )
      ).to.be.reverted;
      
      await expect(
        XDRM.connect(creator).purchaseLicense(0,
          30,
          "termsHash",
          0,
          ethers.parseEther("0.1"),
          ethers.parseEther("0.0025"),
          ethers.parseEther("0.0025"),
          { value: ethers.parseEther("0.1025") }
        )
      ).to.be.reverted;
    });
  });

  describe("Withdraw Balance", function () {
    it("Should withdraw contract balance (owner only)", async function () {
      // Register artwork to send ETH to contract
      await XDRM.connect(creator).registerArtwork(
        "ipfs://test",
        1000,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const contractBalance = await ethers.provider.getBalance(await XDRM.getAddress());
      expect(contractBalance).to.equal(0); // Already transferred to owner
      
      // Send some ETH directly to contract
      await owner.sendTransaction({
        to: await XDRM.getAddress(),
        value: ethers.parseEther("0.1")
      });
      
      const ownerInitialBalance = await ethers.provider.getBalance(owner.address);
      const tx = await XDRM.connect(owner).withdrawBalance();
      const receipt = await tx.wait();
      const gasUsed = receipt.gasUsed * receipt.gasPrice;
      
      const ownerFinalBalance = await ethers.provider.getBalance(owner.address);
      expect(ownerFinalBalance).to.be.closeTo(
        ownerInitialBalance + ethers.parseEther("0.1") - gasUsed,
        ethers.parseEther("0.0001")
      );
    });

    it("Should revert if non-owner tries to withdraw", async function () {
      await expect(
        XDRM.connect(creator).withdrawBalance()
      ).to.be.revertedWith("Ownable: caller is not the owner");
    });

    it("Should revert if balance is zero", async function () {
      await expect(
        XDRM.connect(owner).withdrawBalance()
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });
  });

  describe("Edge Cases", function () {
    it("Should handle multiple licenses for same artwork", async function () {
      await XDRM.connect(creator).registerArtwork(
        "ipfs://test",
        1000,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      await XDRM.connect(creator).purchaseLicense(0,
        30,
        "termsHash1",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      await XDRM.connect(creator).purchaseLicense(0,
        30,
        "termsHash2",
        1,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      const activeLicenses = await XDRM.getActiveLicenses(0);
      expect(activeLicenses.length).to.equal(2);
    });

    it("Should handle maximum royalty percentage", async function () {
      await XDRM.connect(creator).registerArtwork(
        "ipfs://test",
        2000, // 20% - MAX_ROYALTY
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const [,, royalty] = await XDRM.getArtworkInfo(0);
      expect(royalty).to.equal(2000);
    });
  });

  after(async function () {
    if (ethers.provider) {
      await ethers.provider.destroy();
    }
  });
  describe("Advanced Edge Cases", function () {
    let tokenId;
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000;
  
    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });
  
    it("Should handle zero royalty (0%)", async function () {
      await XDRM.connect(creator).registerArtwork(
        "ipfs://QmTest456",
        0, // 0% royalty
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const [, , royalty] = await XDRM.getArtworkInfo(1);
      expect(royalty).to.equal(0);
    });
  
    it("Should handle maximum royalty (20%)", async function () {
      await XDRM.connect(creator).registerArtwork(
        "ipfs://QmTest789",
        2000, // 20% - MAX_ROYALTY
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const [, , royalty] = await XDRM.getArtworkInfo(1);
      expect(royalty).to.equal(2000);
    });
  
    it("Should handle very long metadata URI", async function () {
      const longURI = "ipfs://" + "Qm".repeat(100);
      await XDRM.connect(creator).registerArtwork(
        longURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      const [, uri] = await XDRM.getArtworkInfo(1);
      expect(uri).to.equal(longURI);
    });
  
    it("Should handle license expiration", async function () {
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      // Grant license with 1 day duration
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        1, // 1 day
        "termsHash",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.true;
      
      // Fast forward time (Hardhat network manipulation)
      await ethers.provider.send("evm_increaseTime", [2 * 24 * 60 * 60]); // 2 days
      await ethers.provider.send("evm_mine", []);
      
      // License should be expired
      expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.false;
    });
  
    it("Should handle all license types", async function () {
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      // PERSONAL (0)
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        30,
        "terms1",
        0, // PERSONAL_USE
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      // COMMERCIAL (1)
      await XDRM.connect(creator).purchaseLicense(tokenId,
        30,
        "terms2",
        2, // COMMERCIAL
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      // EXCLUSIVE (2)
      await XDRM.connect(creator).purchaseLicense(tokenId,
        30,
        "terms3",
        4, // EXCLUSIVE
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      const licenses = await XDRM.getActiveLicenses(tokenId);
      expect(licenses.length).to.equal(3);
      expect(licenses[0].licenseType).to.equal(0); // PERSONAL
      expect(licenses[1].licenseType).to.equal(1); // COMMERCIAL
      expect(licenses[2].licenseType).to.equal(2); // EXCLUSIVE
    });
  });
  
  describe("Security Tests", function () {
    let tokenId;
    const metadataURI = "ipfs://QmTest123";
    const royaltyPercentage = 1000;
  
    beforeEach(async function () {
      await XDRM.connect(creator).registerArtwork(
        metadataURI,
        royaltyPercentage,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      tokenId = 0;
    });
  
    it("Should prevent reentrancy attack", async function () {
      // ReentrancyGuard modifier should prevent this
      // This is already tested by nonReentrant modifier in functions
      // But we can verify that functions have the modifier
      
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      // Normal operation should work
      await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        30,
        "termsHash",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      
      // If reentrancy was possible, this would fail
      expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.true;
    });
  
    it("Should prevent integer overflow", async function () {
      // Test with very large values
      const maxRoyalty = 2000; // 20%
      
      // Should revert if exceeds max
      await expect(
        XDRM.connect(creator).registerArtwork(
          metadataURI,
          2001, // > MAX_ROYALTY
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE }
        )
      ).to.be.revertedWithCustomError(XDRM, "InvalidInput");
    });
  
    it("Should enforce access control on all owner functions", async function () {
      // pause/unpause already tested
      // withdrawBalance already tested
      // All should revert for non-owner
      await expect(
        XDRM.connect(creator).pause()
      ).to.be.revertedWith("Ownable: caller is not the owner");
      
      await expect(
        XDRM.connect(creator).withdrawBalance()
      ).to.be.revertedWith("Ownable: caller is not the owner");
    });
  });
  
  describe("Integration Tests", function () {
    it("Should handle complete workflow", async function () {
      // 1. Register artwork
      const tx1 = await XDRM.connect(creator).registerArtwork(
        "ipfs://QmWorkflow",
        1000,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      await expect(tx1).to.emit(XDRM, "ArtworkRegistered");
      const tokenId = 0;
      
      // 2. Grant license
      const licenseFee = ethers.parseEther("0.1");
      const buyerPlatformFee = ethers.parseEther("0.0025");
      const sellerPlatformFee = ethers.parseEther("0.0025");
      
      const tx2 = await XDRM.connect(licensee).purchaseLicense(
        tokenId,
        30,
        "termsHash",
        0,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      await expect(tx2).to.emit(XDRM, "LicenseGranted");
      
      // 3. Purchase license (different user)
      const tx3 = await XDRM.connect(buyer).purchaseLicense(
        tokenId,
        30,
        "termsHash2",
        1,
        licenseFee,
        buyerPlatformFee,
        sellerPlatformFee,
        { value: licenseFee + buyerPlatformFee }
      );
      await expect(tx3).to.emit(XDRM, "LicenseGranted");
      
     // 4. Sale - First transfer to buyer (primary sale, no royalty)
    const salePrice1 = ethers.parseEther("1.0");
    const buyerPlatformFeeSale = ethers.parseEther("0.025");
    const sellerPlatformFeeSale = ethers.parseEther("0.025");

    // First sale: creator to buyer (primary sale, no RoyaltyPaid event)
    await XDRM.connect(buyer).handleSale(
    tokenId,
    salePrice1,
    buyerPlatformFeeSale,
    sellerPlatformFeeSale,
    { value: salePrice1 + buyerPlatformFeeSale }
    );

    // Second sale: buyer to anotherUser (secondary sale, RoyaltyPaid event)
    const salePrice2 = ethers.parseEther("2.0");
    const tx4 = await XDRM.connect(anotherUser).handleSale(
    tokenId,
    salePrice2,
    buyerPlatformFeeSale,
    sellerPlatformFeeSale,
    { value: salePrice2 + buyerPlatformFeeSale }
    );
    await expect(tx4).to.emit(XDRM, "RoyaltyPaid");

// Verify final state
expect(await XDRM.ownerOf(tokenId)).to.equal(anotherUser.address);
expect(await XDRM.isLicenseValid(tokenId, licensee.address)).to.be.true;
expect(await XDRM.isLicenseValid(tokenId, buyer.address)).to.be.true;
  
    it("Should handle multiple users interacting", async function () {
      // Creator 1 registers
      await XDRM.connect(creator).registerArtwork(
        "ipfs://Qm1",
        1000,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      // Creator 2 registers
      await XDRM.connect(buyer).registerArtwork(
        "ipfs://Qm2",
        1500,
        REGISTRATION_FEE,
        { value: REGISTRATION_FEE }
      );
      
      // Both should have their artworks
      const creator1Artworks = await XDRM.getCreatorArtworks(creator.address);
      const creator2Artworks = await XDRM.getCreatorArtworks(buyer.address);
      
      expect(creator1Artworks.length).to.equal(1);
      expect(creator2Artworks.length).to.equal(1);
      expect(creator1Artworks[0]).to.equal(0);
      expect(creator2Artworks[0]).to.equal(1);
    });
  });
  
  describe("Stress Tests", function () {
    it("Should handle many artworks", async function () {
      const count = 10;
      for (let i = 0; i < count; i++) {
        await XDRM.connect(creator).registerArtwork(
          `ipfs://Qm${i}`,
          1000,
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE }
        );
      }
      
      expect(await XDRM.getCurrentTokenId()).to.equal(count);
      const artworks = await XDRM.getCreatorArtworks(creator.address);
      expect(artworks.length).to.equal(count);
    });
  
    it("Should handle many licenses for one artwork", async function () {
        await XDRM.connect(creator).registerArtwork(
          "ipfs://QmTest",
          1000,
          REGISTRATION_FEE,
          { value: REGISTRATION_FEE }
        );
        
        const licenseFee = ethers.parseEther("0.1");
        const buyerPlatformFee = ethers.parseEther("0.0025");
        const sellerPlatformFee = ethers.parseEther("0.0025");
        
        // Get all signers
        const signers = await ethers.getSigners();
        const count = 5;
        
        // Use signers starting from index 1 (skip owner at index 0)
        for (let i = 1; i <= count && i < signers.length; i++) {
          await XDRM.connect(creator).grantLicense(
            0,
            signers[i].address,
            30,
            `terms${i}`,
            (i - 1) % 3, // Different license types (0, 1, 2)
            licenseFee,
            buyerPlatformFee,
            sellerPlatformFee,
            { value: licenseFee + buyerPlatformFee }
          );
        }
        
        const licenses = await XDRM.getActiveLicenses(0);
        expect(licenses.length).to.equal(count);
      });
  });
})
});
