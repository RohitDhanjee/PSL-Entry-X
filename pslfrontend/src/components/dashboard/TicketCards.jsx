import * as React from 'react';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardMedia from '@mui/material/CardMedia';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import CardActionArea from '@mui/material/CardActionArea';
import CardActions from '@mui/material/CardActions';

export default function ArtworkCards({title,date,price,ipfsHash}) {
  return (
    <Card sx={{ maxWidth: 345 }}>
      <CardActionArea>
        <CardMedia
          component="img"
          height="140"
          image="/ticket.jfif"
          alt="ticket"
        />
        <CardContent>
          <Typography gutterBottom variant="h5" component="div">
            {title}
          </Typography>
          <Typography variant="p" sx={{ color: 'text.secondary' }}>
 <br /> Price: ${price} <br /> Date: {date}  <br />IPFS Hash: {ipfsHash}
          </Typography>
        </CardContent>
      </CardActionArea>
      <CardActions className='my-5'>
        <Button size="small" color="secondary">
          Manage Ticket
        </Button>
        <Button size="small" color="secondary" className='ms-5'>
          Download Certificate
        </Button>
      </CardActions>
    </Card>
  );
}
