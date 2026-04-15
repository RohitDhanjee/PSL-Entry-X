import React, { useState, useMemo } from "react";
import PropTypes from "prop-types";
import { alpha, useTheme } from "@mui/material/styles"; // Import useTheme
import Box from "@mui/material/Box";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import TableSortLabel from "@mui/material/TableSortLabel";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import FormControlLabel from "@mui/material/FormControlLabel";
import Switch from "@mui/material/Switch";
import { visuallyHidden } from "@mui/utils";
import Button from "@mui/material/Button";
import SearchIcon from "@mui/icons-material/Search";
import InputAdornment from "@mui/material/InputAdornment";
import TextField from "@mui/material/TextField";



function descendingComparator(a, b, orderBy) {
  if (b[orderBy] < a[orderBy]) return -1;
  if (b[orderBy] > a[orderBy]) return 1;
  return 0;
}

function getComparator(order, orderBy) {
  return order === "desc"
    ? (a, b) => descendingComparator(a, b, orderBy)
    : (a, b) => -descendingComparator(a, b, orderBy);
}



function EnhancedTableHead(props) {
  const { order, orderBy, onRequestSort,headCells } = props;
  const createSortHandler = (property) => (event) => {
    onRequestSort(event, property);
  };

  return (
    <TableHead>
      <TableRow>
        {headCells.map((headCell) => (
          <TableCell
          sx={{fontWeight: "bold"}}
            key={headCell.id}
            align={headCell.numeric ? "right" : "left"}
            padding={headCell.disablePadding ? "none" : "normal"}
            sortDirection={orderBy === headCell.id ? order : false}
          >
            <TableSortLabel
              active={orderBy === headCell.id}
              direction={orderBy === headCell.id ? order : "asc"}
              onClick={createSortHandler(headCell.id)}
            >
              {headCell.label}
              {orderBy === headCell.id ? (
                <Box component="span" sx={visuallyHidden}>
                  {order === "desc" ? "sorted descending" : "sorted ascending"}
                </Box>
              ) : null}
            </TableSortLabel>
          </TableCell>
        ))}
      </TableRow>
    </TableHead>
  );
}

EnhancedTableHead.propTypes = {
  onRequestSort: PropTypes.func.isRequired,
  order: PropTypes.oneOf(["asc", "desc"]).isRequired,
  orderBy: PropTypes.string.isRequired,
  headCells: PropTypes.array.isRequired,
};

function EnhancedTableToolbar({ searchQuery, onSearchChange }) {
  const theme = useTheme(); // Access the current theme

  return (
    <Toolbar
      sx={{
        pl: { sm: 2 },
        pr: { xs: 1, sm: 1 },
        display: "flex",
        flexDirection: { xs: "column", sm: "row" },
        justifyContent: { sm: "space-between" },
        alignItems: "center",
        gap: { xs: 2, sm: 1 },
      }}
    >

      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", sm: "row" },
          alignItems: "center",
          gap: 1,
          width: "100%",
          maxWidth: "50%", // Ensure no scroll by limiting the width
        }}
      >
        <TextField
          variant="outlined"
          size="small"
          placeholder="Search..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                {/* <SearchIcon /> */}
              </InputAdornment>
            ),
          }}
          sx={{
            width: "100%",
            backgroundColor:
              theme.palette.mode === "dark" ? "#424242" : "#f9f9f9", // Adjust background color based on theme
            borderRadius: "4px",
            "& .MuiOutlinedInput-root": {
              color: theme.palette.text.primary, // Adjust text color
              "& fieldset": {
                borderColor: theme.palette.divider, // Adjust border color
              },
              "&:hover fieldset": {
                borderColor: theme.palette.text.secondary, // Adjust hover border color
              },
            },
          }}
        />
        {/* <Button
          variant="contained"
          sx={{
            backgroundColor: "#8200DB", // Set button color
            "&:hover": {
              backgroundColor: "#6A00B8", // Darken color on hover
            },
            width: { xs: "100%", sm: "auto" },
            overflow: "hidden", // Prevent scrollbars
            textOverflow: "ellipsis", // Handle text overflow gracefully
            whiteSpace: "nowrap", // Prevent text wrapping
          }}
          // startIcon={<SearchIcon />}
          onClick={() => onSearchChange(searchQuery)}
        >
          Search
        </Button> */}
      </Box>
    </Toolbar>
  );
}

EnhancedTableToolbar.propTypes = {
  searchQuery: PropTypes.string.isRequired,
  onSearchChange: PropTypes.func.isRequired,
};

export default function DataTable({ rows, headCells }) {
  const [order, setOrder] = useState("asc");
  const [orderBy, setOrderBy] = useState("date");
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(5);
  const [searchQuery, setSearchQuery] = useState("");

  const handleRequestSort = (event, property) => {
    const isAsc = orderBy === property && order === "asc";
    setOrder(isAsc ? "desc" : "asc");
    setOrderBy(property);
  };

  const handleChangePage = (event, newPage) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (event) => {
    setRowsPerPage(parseInt(event.target.value, 10));
    setPage(0);
  };

  const handleSearchChange = (query) => {
    setSearchQuery(query);
    setPage(0);
  };

  const filteredRows = useMemo(() => {
    return rows.filter((row) =>
      Object.values(row).some((value) =>
        value.toString().toLowerCase().includes(searchQuery.toLowerCase())
      )
    );
  }, [searchQuery]);

  const emptyRows = Math.max(0, (1 + page) * rowsPerPage - filteredRows.length);

  const visibleRows = useMemo(
    () =>
      [...filteredRows]
        .sort(getComparator(order, orderBy))
        .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage),
    [order, orderBy, page, rowsPerPage, filteredRows]
  );

  return (
    <Box
      sx={{
        width: "100%",
        boxSizing: "border-box",
        padding: { xs: 2, md: 4 },
        marginTop: { xs: 5, md: 2 },
        overflowX: "auto", // Add horizontal scroll for the entire page
      }}
    >
      <Paper
        sx={{
          width: "100%",
          mb: 2,
          padding: { xs: 2, sm: 5 },
        }}
      >
        <EnhancedTableToolbar
          searchQuery={searchQuery}
          onSearchChange={handleSearchChange}
        />
        <TableContainer
          sx={{
            maxHeight: "400px", // Set a max height for the table container
            overflowY: "auto", // Enable vertical scrolling for the table
          }}
        >
          <Table
            sx={{ minWidth: 750 }}
            aria-labelledby="tableTitle"
            size="medium"
          >
            <EnhancedTableHead
              order={order}
  orderBy={orderBy}
  onRequestSort={handleRequestSort}
  headCells={headCells}
            />
            <TableBody>
              {visibleRows.map((row) => (
    <TableRow key={row.id} hover>
      {headCells.map((cell) => (
        <TableCell key={cell.id} padding={cell.disablePadding ? "none" : "normal"}>
          {row[cell.id]}
        </TableCell>
      ))}
    </TableRow>
  ))}
              {emptyRows > 0 && (
                <TableRow style={{ height: 53 * emptyRows }}>
                  <TableCell colSpan={6} />
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[5, 8]}
          component="div"
          count={filteredRows.length}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={handleChangePage}
          onRowsPerPageChange={handleChangeRowsPerPage}
        />
      </Paper>
    </Box>
  );
}